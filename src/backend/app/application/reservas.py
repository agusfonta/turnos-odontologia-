"""Caso de uso: reservar un turno (C-04, design Decision 7). Todo `def`.

Flujo: validar (404/422) -> chequeo de ocupacion de aplicacion -> insertar
paciente + turno + auditoria `crear` en UNA transaccion -> commit. La garantia
bajo concurrencia es la exclusion constraint de la DB (sqlstate 23P01), que se
traduce al mismo 409 tras rollback. El 409 recalcula los huecos FUERA de la
transaccion fallida. Sin locks pesimistas.
"""

import secrets
import uuid
from datetime import datetime, timedelta
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
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import (
    AuditoriaActor,
    AuditoriaTurno,
    Paciente,
    Profesional,
    Tratamiento,
    Turno,
    TurnoOrigen,
    User,
)
from app.infrastructure.repositories import BaseRepository
from app.infrastructure.repositories_agenda import (
    BloqueoRepository,
    HorarioRepository,
    TurnoRepository,
)

EXCLUSION_VIOLATION = "23P01"


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
    session: Session, datos: TurnoCreate, *, ahora: datetime, tz: ZoneInfo
) -> HuecoOcupadoError:
    session.rollback()  # la transaccion fallida se cierra antes de releer
    return HuecoOcupadoError(_huecos_actualizados(session, datos, ahora=ahora, tz=tz))


def reservar_turno(
    session: Session,
    datos: TurnoCreate,
    *,
    staff: User | None,
    ahora: datetime,
    tz: ZoneInfo,
) -> Turno:
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
    if not es_inicio_valido(datos.inicio, franjas, profesional.slot_default_min, duracion_min, ahora, tz):
        raise InicioInvalidoError()

    fin = datos.inicio + timedelta(minutes=duracion_min)
    if hay_ocupacion(session, datos.profesional_id, datos.inicio, fin):
        raise _conflicto(session, datos, ahora=ahora, tz=tz)

    es_secretaria = staff is not None
    try:
        paciente = Paciente(nombre=datos.paciente_nombre, telefono=datos.paciente_telefono)
        session.add(paciente)
        session.flush()
        turno = Turno(
            profesional_id=datos.profesional_id,
            paciente_id=paciente.id,
            tratamiento_id=datos.tratamiento_id,
            inicio=datos.inicio,
            fin=fin,
            estado=EstadoTurno.RESERVADO,
            origen=TurnoOrigen.SECRETARIA if es_secretaria else TurnoOrigen.ONLINE,
            token_publico=secrets.token_urlsafe(32),
            created_by=staff.id if staff else None,
        )
        session.add(turno)
        session.flush()  # aca salta la exclusion constraint si hubo carrera
        session.add(
            AuditoriaTurno(
                turno_id=turno.id,
                accion="crear",
                actor_tipo=AuditoriaActor.SECRETARIA if es_secretaria else AuditoriaActor.PACIENTE,
                actor_user_id=staff.id if staff else None,
                detalle={"origen": turno.origen.value},
            )
        )
        session.commit()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != EXCLUSION_VIOLATION:
            raise  # otra violacion = bug (500), no se enmascara como 409
        raise _conflicto(session, datos, ahora=ahora, tz=tz) from exc
    return turno
