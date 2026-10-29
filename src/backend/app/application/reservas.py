"""Caso de uso: reservar un turno (C-04 Decision 7, C-04b UoW). Todo `def`.

Flujo: validar (404/422) -> chequeo de ocupacion de aplicacion -> insertar
paciente + turno + auditoria `crear` en UNA transaccion. La garantia bajo
concurrencia es la exclusion constraint de la DB: el turno se inserta con
`ON CONFLICT ON CONSTRAINT ex_turnos_sin_solape DO NOTHING`
(`TurnoRepository.insertar_si_no_solapa`), que la usa como arbitro sin el
deadlock 40P01 que un INSERT comun sufre entre altas solapadas concurrentes;
"sin fila" -> 409. Un 23P01 (p.ej. en el COMMIT) tambien es 409. Sin locks pesimistas.

Patron para los casos de uso de escritura (C-05, C-07), copiar tal cual:

* Reciben una `uow_factory` (`UowFactory`, dependencia `get_uow_factory`) y abren
  `with uow_factory() as session:` ADENTRO. NUNCA llaman `commit`/`rollback`: el
  bloque `with` es el unico dueño de la transaccion (lo vigila
  `tests/test_transacciones_arquitectura.py`).
* Hacen un `flush()` final dentro del `with`, para que todo error de datos salga
  antes del COMMIT de `__exit__`.
* Devuelven un DTO (dataclass) armado DENTRO del `with`; ninguna entidad ORM
  cruza el limite de la transaccion.
* El `try/except IntegrityError` envuelve el `with` completo (cubre tambien un
  fallo en el COMMIT). Para releer tras un conflicto se abre una UoW NUEVA una vez
  que la fallida ya hizo rollback y close.
* Efectos externos (Redis, etc.) los dispara el router DESPUES de que el caso de
  uso retorno (= ya hubo commit).
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.disponibilidad import consultar_disponibilidad
from app.core.exceptions import (
    HuecoOcupadoError,
    InicioInvalidoError,
    ProfesionalNoEncontradoError,
    TratamientoNoEncontradoError,
)
from app.core.settings import get_settings
from app.domain.disponibilidad import es_inicio_valido
from app.domain.schemas import HuecoPublico, TurnoCreate
from app.infrastructure.models import (
    AuditoriaActor,
    AuditoriaTurno,
    Paciente,
    Profesional,
    Tratamiento,
    TurnoOrigen,
)
from app.infrastructure.repositories import BaseRepository
from app.infrastructure.repositories_agenda import (
    BloqueoRepository,
    HorarioRepository,
    TurnoRepository,
)
from app.infrastructure.unit_of_work import UowFactory

EXCLUSION_VIOLATION = "23P01"


@dataclass(frozen=True, slots=True)
class TurnoReservado:
    """DTO de aplicacion: lo que el router necesita, sin entidades ORM."""

    id: uuid.UUID
    profesional_id: uuid.UUID
    tratamiento_id: int | None
    inicio: datetime
    fin: datetime
    origen: Literal["online", "secretaria"]
    token_publico: str


class _HuecoOcupado(Exception):
    """Señal interna: el chequeo de aplicacion vio ocupacion (no sale del modulo)."""


def hay_ocupacion(
    session: Session, profesional_id: uuid.UUID, inicio: datetime, fin: datetime
) -> bool:
    """Chequeo de aplicacion: turno no cancelado o bloqueo activo que pise `[inicio, fin)`."""
    return bool(
        TurnoRepository(session).ocupados_en_rango(profesional_id, inicio, fin)
        or BloqueoRepository(session).ocupados_en_rango(profesional_id, inicio, fin)
    )


def _huecos_actualizados(
    session: Session,
    datos: TurnoCreate,
    *,
    ahora: datetime,
    tz: ZoneInfo,
) -> list[dict[str, str]]:
    dia = datos.inicio.astimezone(tz).date()
    huecos = consultar_disponibilidad(
        session,
        profesional_id=datos.profesional_id,
        desde=dia,
        hasta=dia,
        tratamiento_id=datos.tratamiento_id,
        ahora=ahora,
        tz=tz,
        max_dias=get_settings().DISPONIBILIDAD_MAX_DIAS,
    )
    return [HuecoPublico.model_validate(h).model_dump(mode="json") for h in huecos]


def _conflicto(
    uow_factory: UowFactory, datos: TurnoCreate, *, ahora: datetime, tz: ZoneInfo
) -> HuecoOcupadoError:
    """409 con huecos leidos en una UoW NUEVA, cuando la transaccion fallida ya se cerro."""
    with uow_factory() as lectura:
        return HuecoOcupadoError(_huecos_actualizados(lectura, datos, ahora=ahora, tz=tz))


def reservar_turno(
    uow_factory: UowFactory,
    datos: TurnoCreate,
    *,
    staff_id: uuid.UUID | None,
    ahora: datetime,
    tz: ZoneInfo,
) -> TurnoReservado:
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
            if hay_ocupacion(session, datos.profesional_id, datos.inicio, fin):
                raise _HuecoOcupado()

            es_secretaria = staff_id is not None
            origen = TurnoOrigen.SECRETARIA if es_secretaria else TurnoOrigen.ONLINE
            token_publico = secrets.token_urlsafe(32)
            paciente = Paciente(nombre=datos.paciente_nombre, telefono=datos.paciente_telefono)
            session.add(paciente)
            session.flush()
            # La exclusion constraint decide la carrera (ON CONFLICT, sin deadlock 40P01):
            # None = solape con un turno ya confirmado -> 409 tras el rollback del `with`.
            turno_id = TurnoRepository(session).insertar_si_no_solapa(
                profesional_id=datos.profesional_id,
                paciente_id=paciente.id,
                tratamiento_id=datos.tratamiento_id,
                inicio=datos.inicio,
                fin=fin,
                origen=origen,
                token_publico=token_publico,
                created_by=staff_id,
            )
            if turno_id is None:
                raise _HuecoOcupado()
            session.add(
                AuditoriaTurno(
                    turno_id=turno_id,
                    accion="crear",
                    actor_tipo=AuditoriaActor.SECRETARIA if es_secretaria else AuditoriaActor.PACIENTE,
                    actor_user_id=staff_id,
                    detalle={"origen": origen.value},
                )
            )
            session.flush()  # todo error de datos sale aca, antes del COMMIT de __exit__
            reservado = TurnoReservado(
                id=turno_id,
                profesional_id=datos.profesional_id,
                tratamiento_id=datos.tratamiento_id,
                inicio=datos.inicio,
                fin=fin,
                origen="secretaria" if es_secretaria else "online",
                token_publico=token_publico,
            )
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != EXCLUSION_VIOLATION:
            raise  # otra violacion = bug (500), no se enmascara como 409
        raise _conflicto(uow_factory, datos, ahora=ahora, tz=tz) from exc
    except _HuecoOcupado:
        raise _conflicto(uow_factory, datos, ahora=ahora, tz=tz) from None
    return reservado
