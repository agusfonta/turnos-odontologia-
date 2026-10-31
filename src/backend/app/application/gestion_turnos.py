"""Casos de uso de gestion de turnos (C-05): alta manual, reprogramar, cancelar; C-07: confirmar.

Mismo patron que `reservas.py` (C-04b): reciben una `uow_factory`, abren
`with uow_factory() as session:` ADENTRO, NUNCA llaman `commit`/`rollback`, hacen un
`flush()` final dentro del `with`, devuelven un DTO armado dentro del `with` y dejan los
efectos externos (Redis) al router, DESPUES del retorno (= ya hubo commit).

Actor: `Actor(tipo, user_id)`. La secretaria (DD-05) esta exenta de la anticipacion minima;
el actor paciente entra por la puerta de token (`app/application/autogestion.py`, C-07).

Orden de locks en `reprogramar_turno` (evita ciclos, D4):
  1. `profesional_de(turno_id)` SIN lock (404 si no existe);
  2. advisory lock transaccional del profesional (`bloquear_agenda`);
  3. `SELECT ... FOR UPDATE` del turno (relee el estado vigente);
  4. validaciones + UPDATE + auditoria + `flush()`.
`alta_manual_turno` toma solo (2). `cancelar_turno` solo (3): libera agenda, no la ocupa.
La exclusion `ex_turnos_sin_solape` sigue siendo el arbitro: 23P01 y 40P01 -> 409.
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.application import reservas
from app.core.exceptions import (
    AnticipacionInsuficienteError,
    HuecoOcupadoError,
    InicioInvalidoError,
    ProfesionalNoEncontradoError,
    TransicionNoPermitidaError,
    TratamientoNoEncontradoError,
    TurnoNoEncontradoError,
)
from app.core.settings import get_settings
from app.domain.anticipacion import verificar_anticipacion
from app.domain.disponibilidad import es_inicio_valido
from app.domain.schemas import TurnoManualCreate, TurnoReprogramar
from app.domain.turno_estados import (
    EstadoTurno,
    TransicionInvalidaError,
    estado_tras_reprogramar,
    transicionar,
)
from app.infrastructure.models import (
    AuditoriaActor,
    AuditoriaTurno,
    Paciente,
    Profesional,
    Tratamiento,
    Turno,
    TurnoOrigen,
)
from app.infrastructure.repositories import BaseRepository, PacienteRepository
from app.infrastructure.repositories_agenda import (
    BloqueoRepository,
    HorarioRepository,
    TurnoRepository,
)
from app.infrastructure.unit_of_work import UowFactory

logger = logging.getLogger(__name__)

SQLSTATES_DE_CONFLICTO = frozenset({reservas.EXCLUSION_VIOLATION, "40P01"})


@dataclass(frozen=True, slots=True)
class Actor:
    """Quien opera: `SECRETARIA` + id de usuario; `PACIENTE` + `None` (C-07)."""

    tipo: AuditoriaActor
    user_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class TurnoManualCreadoDTO:
    id: uuid.UUID
    profesional_id: uuid.UUID
    paciente_id: uuid.UUID
    tratamiento_id: int | None
    inicio: datetime
    fin: datetime
    origen: Literal["secretaria"]
    sobreturno: bool
    token_publico: str


@dataclass(frozen=True, slots=True)
class TurnoGestionado:
    id: uuid.UUID
    profesional_id: uuid.UUID
    paciente_id: uuid.UUID
    tratamiento_id: int | None
    inicio: datetime
    fin: datetime
    estado: EstadoTurno
    origen: Literal["online", "secretaria"]
    sobreturno: bool


class _HuecoOcupado(Exception):
    """Señal interna: el chequeo de aplicacion vio ocupacion (no sale del modulo)."""


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


def _gestionado(turno: Turno) -> TurnoGestionado:
    return TurnoGestionado(
        id=turno.id,
        profesional_id=turno.profesional_id,
        paciente_id=turno.paciente_id,
        tratamiento_id=turno.tratamiento_id,
        inicio=turno.inicio,
        fin=turno.fin,
        estado=turno.estado,
        origen=turno.origen.value,  # type: ignore[arg-type]
        sobreturno=turno.sobreturno,
    )


def _ocupado(
    session: Session,
    profesional_id: uuid.UUID,
    inicio: datetime,
    fin: datetime,
    *,
    sobreturno: bool,
    excluir_turno_id: uuid.UUID | None = None,
) -> bool:
    """Sin marca: turnos + bloqueos. Con `sobreturno`: solo bloqueos (D3, nunca se salta uno)."""
    if sobreturno:
        return bool(BloqueoRepository(session).ocupados_en_rango(profesional_id, inicio, fin))
    return reservas.hay_ocupacion(
        session, profesional_id, inicio, fin, excluir_turno_id=excluir_turno_id
    )


def alta_manual_turno(
    uow_factory: UowFactory,
    datos: TurnoManualCreate,
    *,
    staff_id: uuid.UUID,
    ahora: datetime,
    tz: ZoneInfo,
) -> TurnoManualCreadoDTO:
    """Alta por secretaria: reusa paciente por telefono (DD-06) y admite `sobreturno`."""
    try:
        with uow_factory() as session:
            profesional = BaseRepository(session, Profesional).get(datos.profesional_id)
            if profesional is None or not profesional.is_active:
                raise ProfesionalNoEncontradoError()
            duracion_min = profesional.slot_default_min
            if datos.tratamiento_id is not None:
                tratamiento = BaseRepository(session, Tratamiento).get(datos.tratamiento_id)
                if tratamiento is None or not tratamiento.is_active:
                    raise TratamientoNoEncontradoError()
                duracion_min = tratamiento.duracion_min

            franjas = HorarioRepository(session).activas_por_profesional(datos.profesional_id)
            if not es_inicio_valido(
                datos.inicio, franjas, profesional.slot_default_min, duracion_min, ahora, tz
            ):
                raise InicioInvalidoError()

            fin = datos.inicio + timedelta(minutes=duracion_min)
            turnos = TurnoRepository(session)
            turnos.bloquear_agenda(datos.profesional_id)
            if _ocupado(
                session, datos.profesional_id, datos.inicio, fin, sobreturno=datos.sobreturno
            ):
                raise _HuecoOcupado()

            paciente = PacienteRepository(session).buscar_por_telefono(datos.paciente_telefono)
            reutilizado = paciente is not None
            if paciente is None:
                paciente = Paciente(nombre=datos.paciente_nombre, telefono=datos.paciente_telefono)
                session.add(paciente)
                session.flush()

            token_publico = secrets.token_urlsafe(32)
            turno_id = turnos.insertar_si_no_solapa(
                profesional_id=datos.profesional_id,
                paciente_id=paciente.id,
                tratamiento_id=datos.tratamiento_id,
                inicio=datos.inicio,
                fin=fin,
                origen=TurnoOrigen.SECRETARIA,
                token_publico=token_publico,
                created_by=staff_id,
                sobreturno=datos.sobreturno,
            )
            if turno_id is None:
                raise _HuecoOcupado()
            session.add(
                AuditoriaTurno(
                    turno_id=turno_id,
                    accion="crear",
                    actor_tipo=AuditoriaActor.SECRETARIA,
                    actor_user_id=staff_id,
                    detalle={
                        "origen": "secretaria",
                        "sobreturno": datos.sobreturno,
                        "paciente_reutilizado": reutilizado,
                    },
                )
            )
            session.flush()  # todo error de datos sale aca, antes del COMMIT de __exit__
            creado = TurnoManualCreadoDTO(
                id=turno_id,
                profesional_id=datos.profesional_id,
                paciente_id=paciente.id,
                tratamiento_id=datos.tratamiento_id,
                inicio=datos.inicio,
                fin=fin,
                origen="secretaria",
                sobreturno=datos.sobreturno,
                token_publico=token_publico,
            )
    except DBAPIError as exc:
        if _sqlstate(exc) not in SQLSTATES_DE_CONFLICTO:
            raise  # otra violacion = bug (500), no se enmascara como 409
        raise reservas.conflicto_hueco(
            uow_factory,
            datos.profesional_id,
            datos.inicio.astimezone(tz).date(),
            datos.tratamiento_id,
            ahora=ahora,
            tz=tz,
        ) from exc
    except _HuecoOcupado:
        raise reservas.conflicto_hueco(
            uow_factory,
            datos.profesional_id,
            datos.inicio.astimezone(tz).date(),
            datos.tratamiento_id,
            ahora=ahora,
            tz=tz,
        ) from None
    return creado


def _min_horas() -> int:
    return get_settings().CANCEL_MIN_HOURS


def cancelar_turno(
    uow_factory: UowFactory,
    turno_id: uuid.UUID,
    *,
    actor: Actor,
    ahora: datetime,
) -> TurnoGestionado:
    """Baja logica (`estado=cancelado`): libera el horario. Solo `reservado`/`confirmado`."""
    with uow_factory() as session:
        turno = TurnoRepository(session).obtener_para_actualizar(turno_id)
        if turno is None:
            raise TurnoNoEncontradoError()
        estado_anterior = turno.estado
        try:
            nuevo_estado = transicionar(estado_anterior, EstadoTurno.CANCELADO)
        except TransicionInvalidaError as exc:
            raise TransicionNoPermitidaError(exc.actual.value) from exc
        exento = verificar_anticipacion(
            turno.inicio, ahora, actor_tipo=actor.tipo, min_horas=_min_horas()
        )
        turno.estado = nuevo_estado
        session.add(
            AuditoriaTurno(
                turno_id=turno.id,
                accion="cancelar",
                actor_tipo=actor.tipo,
                actor_user_id=actor.user_id,
                detalle={
                    "estado_anterior": estado_anterior.value,
                    "exento_anticipacion": exento,
                },
            )
        )
        session.flush()
        return _gestionado(turno)


def confirmar_turno(
    uow_factory: UowFactory,
    turno_id: uuid.UUID,
    *,
    actor: Actor,
    ahora: datetime,
) -> TurnoGestionado:
    """`reservado` -> `confirmado` (C-07 D2), unico para la puerta por token y la de secretaria.

    Orden: (1) `FOR UPDATE` (404); (2) ya `confirmado` -> DTO sin auditoria (no-op idempotente);
    (3) `transicionar` (terminal -> 422 transicion); (4) `inicio <= ahora` -> 422 anticipacion
    con `min_horas=0`; (5) auditoria `confirmar` + `flush()`. No toma el advisory lock (no ocupa
    agenda) y NO aplica `CANCEL_MIN_HOURS`: confirmar dentro de la ventana esta permitido.
    """
    with uow_factory() as session:
        turno = TurnoRepository(session).obtener_para_actualizar(turno_id)
        if turno is None:
            raise TurnoNoEncontradoError()
        estado_anterior = turno.estado
        if estado_anterior is EstadoTurno.CONFIRMADO:
            return _gestionado(turno)
        try:
            nuevo_estado = transicionar(estado_anterior, EstadoTurno.CONFIRMADO)
        except TransicionInvalidaError as exc:
            raise TransicionNoPermitidaError(exc.actual.value) from exc
        if turno.inicio <= ahora:
            raise AnticipacionInsuficienteError(0)
        turno.estado = nuevo_estado
        session.add(
            AuditoriaTurno(
                turno_id=turno.id,
                accion="confirmar",
                actor_tipo=actor.tipo,
                actor_user_id=actor.user_id,
                detalle={"estado_anterior": estado_anterior.value},
            )
        )
        session.flush()
        return _gestionado(turno)


def _iso_utc(valor: datetime) -> str:
    return valor.astimezone(timezone.utc).isoformat()


def reprogramar_turno(
    uow_factory: UowFactory,
    turno_id: uuid.UUID,
    datos: TurnoReprogramar,
    *,
    actor: Actor,
    ahora: datetime,
    tz: ZoneInfo,
) -> TurnoGestionado:
    """Mueve el turno a otro hueco del mismo profesional, conservando duracion y tratamiento.

    `confirmado` vuelve a `reservado` (DD-07). Con `sobreturno=True` (solo secretaria) se omite
    la ocupacion por turnos, nunca los bloqueos ni la grilla/franja.
    """
    if datos.sobreturno and actor.tipo is not AuditoriaActor.SECRETARIA:
        raise ValueError("solo la secretaria puede marcar sobreturno")
    contexto: dict[str, object] = {}
    try:
        with uow_factory() as session:
            turnos = TurnoRepository(session)
            profesional_id = turnos.profesional_de(turno_id)  # (1) sin lock
            if profesional_id is None:
                raise TurnoNoEncontradoError()
            turnos.bloquear_agenda(profesional_id)  # (2) advisory lock del profesional
            turno = turnos.obtener_para_actualizar(turno_id)  # (3) FOR UPDATE, estado vigente
            if turno is None:
                raise TurnoNoEncontradoError()
            contexto["tratamiento_id"] = turno.tratamiento_id
            contexto["profesional_id"] = profesional_id

            try:
                estado_nuevo = estado_tras_reprogramar(turno.estado)
            except TransicionInvalidaError as exc:
                raise TransicionNoPermitidaError(exc.actual.value) from exc
            exento = verificar_anticipacion(
                turno.inicio, ahora, actor_tipo=actor.tipo, min_horas=_min_horas()
            )

            profesional = BaseRepository(session, Profesional).get(profesional_id)
            if profesional is None or not profesional.is_active:
                raise ProfesionalNoEncontradoError()
            duracion = turno.fin - turno.inicio
            franjas = HorarioRepository(session).activas_por_profesional(profesional_id)
            if not es_inicio_valido(
                datos.inicio,
                franjas,
                profesional.slot_default_min,
                int(duracion.total_seconds() // 60),
                ahora,
                tz,
            ):
                raise InicioInvalidoError()

            fin_nuevo = datos.inicio + duracion
            if _ocupado(
                session,
                profesional_id,
                datos.inicio,
                fin_nuevo,
                sobreturno=datos.sobreturno,
                excluir_turno_id=turno.id,
            ):
                raise _HuecoOcupado()

            detalle = {
                "inicio_anterior": _iso_utc(turno.inicio),
                "fin_anterior": _iso_utc(turno.fin),
                "inicio_nuevo": _iso_utc(datos.inicio),
                "fin_nuevo": _iso_utc(fin_nuevo),
                "estado_anterior": turno.estado.value,
                "estado_nuevo": estado_nuevo.value,
                "sobreturno": datos.sobreturno,
                "exento_anticipacion": exento,
            }
            turno.inicio = datos.inicio
            turno.fin = fin_nuevo
            turno.estado = estado_nuevo
            turno.sobreturno = datos.sobreturno
            session.add(
                AuditoriaTurno(
                    turno_id=turno.id,
                    accion="reprogramar",
                    actor_tipo=actor.tipo,
                    actor_user_id=actor.user_id,
                    detalle=detalle,
                )
            )
            session.flush()  # el UPDATE verifica la exclusion antes del COMMIT de __exit__
            resultado = _gestionado(turno)
    except DBAPIError as exc:
        sqlstate = _sqlstate(exc)
        if sqlstate not in SQLSTATES_DE_CONFLICTO or "profesional_id" not in contexto:
            raise  # otra violacion = bug (500), no se enmascara como 409
        if sqlstate == "40P01":
            logger.warning(
                "deadlock 40P01 al reprogramar turno_id=%s: se responde 409", turno_id
            )
        raise _conflicto_reprogramar(uow_factory, contexto, datos, ahora=ahora, tz=tz) from exc
    except _HuecoOcupado:
        raise _conflicto_reprogramar(uow_factory, contexto, datos, ahora=ahora, tz=tz) from None
    return resultado


def _conflicto_reprogramar(
    uow_factory: UowFactory,
    contexto: dict[str, object],
    datos: TurnoReprogramar,
    *,
    ahora: datetime,
    tz: ZoneInfo,
) -> HuecoOcupadoError:
    """409 con los huecos del NUEVO dia, en una UoW nueva (la fallida ya hizo rollback)."""
    return reservas.conflicto_hueco(
        uow_factory,
        contexto["profesional_id"],  # type: ignore[arg-type]
        datos.inicio.astimezone(tz).date(),
        contexto["tratamiento_id"],  # type: ignore[arg-type]
        ahora=ahora,
        tz=tz,
    )
