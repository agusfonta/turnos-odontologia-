"""Capa de token de autogestion del paciente (C-07): puerta publica sobre los casos de uso de C-05.

El paciente no se autentica: el secreto es `turnos.token_publico` (256 bits, `token_urlsafe(32)`).
Cada operacion hace dos pasos:

1. `resolver_token`: valida el formato (`TOKEN_RE`) y busca `token -> id` en una UoW de
   LECTURA. Un token malformado ni siquiera abre la UoW. Cualquier token invalido (malformado o
   inexistente) lanza el MISMO `TurnoNoEncontradoError` (404 uniforme, sin fuga de datos).
2. Llama al caso de uso existente (`cancelar_turno`, `reprogramar_turno`, `confirmar_turno`)
   con `Actor(AuditoriaActor.PACIENTE, None)`, que relee el estado con `FOR UPDATE`.

Por que dos transacciones son seguras: el token es inmutable (ninguna operacion lo cambia) y los
turnos no se borran fisicamente (baja logica), asi que `token -> id` no puede variar entre la
lectura y la escritura. Estos casos de uso NO abren transacciones propias ni las confirman: los
delegados lo hacen dentro de su UoW. Todo `def`; los efectos en Redis los hace el router.
El token nunca se loguea.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.application.gestion_turnos import (
    Actor,
    TurnoGestionado,
    cancelar_turno,
    confirmar_turno,
    reprogramar_turno,
)
from app.core.exceptions import TurnoNoEncontradoError
from app.core.settings import get_settings
from app.domain.schemas import TurnoReprogramar, TurnoReprogramarPublico
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import AuditoriaActor
from app.infrastructure.repositories_agenda import TurnoRepository
from app.infrastructure.unit_of_work import UowFactory

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # `token_urlsafe` + largo de la columna
ACTOR_PACIENTE = Actor(AuditoriaActor.PACIENTE, None)


@dataclass(frozen=True, slots=True)
class TurnoPublicoDTO:
    """Detalle de lectura para el paciente: sin `id`, datos del paciente ni token."""

    inicio: datetime
    fin: datetime
    estado: EstadoTurno
    profesional_id: uuid.UUID
    profesional_nombre: str
    tratamiento_id: int | None
    tratamiento_nombre: str | None
    gestionable_hasta: datetime


def gestionable_hasta(inicio: datetime) -> datetime:
    """Ultimo instante en que el paciente puede cancelar/reprogramar (`CANCEL_MIN_HOURS`)."""
    return inicio - timedelta(hours=get_settings().CANCEL_MIN_HOURS)


def resolver_token(uow_factory: UowFactory, token: str) -> uuid.UUID:
    """`token -> turno_id`; cualquier token invalido lanza el mismo `TurnoNoEncontradoError`."""
    if TOKEN_RE.fullmatch(token) is None:  # fullmatch: `$` aceptaria un salto de linea final
        raise TurnoNoEncontradoError()
    with uow_factory() as session:
        turno_id = TurnoRepository(session).id_por_token(token)
    if turno_id is None:
        raise TurnoNoEncontradoError()
    return turno_id


def consultar_por_token(uow_factory: UowFactory, token: str) -> TurnoPublicoDTO:
    """Detalle publico del turno (cualquier estado) en UNA UoW de solo lectura."""
    if TOKEN_RE.fullmatch(token) is None:
        raise TurnoNoEncontradoError()
    with uow_factory() as session:
        repo = TurnoRepository(session)
        turno_id = repo.id_por_token(token)
        detalle = repo.detalle_publico(turno_id) if turno_id is not None else None
        if detalle is None:
            raise TurnoNoEncontradoError()
        return TurnoPublicoDTO(
            inicio=detalle.inicio,
            fin=detalle.fin,
            estado=detalle.estado,
            profesional_id=detalle.profesional_id,
            profesional_nombre=detalle.profesional_nombre,
            tratamiento_id=detalle.tratamiento_id,
            tratamiento_nombre=detalle.tratamiento_nombre,
            gestionable_hasta=gestionable_hasta(detalle.inicio),
        )


def confirmar_por_token(uow_factory: UowFactory, token: str, *, ahora: datetime) -> TurnoGestionado:
    turno_id = resolver_token(uow_factory, token)
    return confirmar_turno(uow_factory, turno_id, actor=ACTOR_PACIENTE, ahora=ahora)


def cancelar_por_token(uow_factory: UowFactory, token: str, *, ahora: datetime) -> TurnoGestionado:
    turno_id = resolver_token(uow_factory, token)
    return cancelar_turno(uow_factory, turno_id, actor=ACTOR_PACIENTE, ahora=ahora)


def reprogramar_por_token(
    uow_factory: UowFactory,
    token: str,
    datos: TurnoReprogramarPublico,
    *,
    ahora: datetime,
    tz: ZoneInfo,
) -> TurnoGestionado:
    """El paciente nunca marca `sobreturno`: se fuerza `False`."""
    turno_id = resolver_token(uow_factory, token)
    return reprogramar_turno(
        uow_factory,
        turno_id,
        TurnoReprogramar(inicio=datos.inicio, sobreturno=False),
        actor=ACTOR_PACIENTE,
        ahora=ahora,
        tz=tz,
    )
