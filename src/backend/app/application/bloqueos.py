"""Casos de uso de bloqueos de agenda (C-06): alta y baja logica por secretaria.

Mismo patron que `reservas.py` / `gestion_turnos.py`: reciben una `uow_factory`, abren
`with uow_factory() as session:` ADENTRO, NUNCA llaman `commit`/`rollback`, hacen un `flush()`
final dentro del `with` y devuelven un DTO armado dentro del `with`. No hay efectos
post-commit (no hay cola involucrada); la trazabilidad es un log estructurado del router.

Invariante "ningun turno activo dentro de un bloqueo activo" (DD-08): lo garantiza la base con
los triggers de la migracion 003. Orden de locks en `crear_bloqueo` (sin ciclos):
  1. advisory lock transaccional del profesional (`bloquear_agenda`, la MISMA clave que usan
     `alta_manual_turno`, `reprogramar_turno` y los triggers; reentrante);
  2. chequeo de aplicacion de turnos activos en el rango (da el 409 con detalle util);
  3. `INSERT` del bloqueo (el trigger `tg_bloqueos_sin_turnos` re-chequea como arbitro).
`dar_de_baja_bloqueo` libera agenda: solo `SELECT ... FOR UPDATE` del bloqueo, sin advisory lock.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.exc import DBAPIError

from app.application import reservas
from app.core.exceptions import (
    BloqueoConTurnosError,
    BloqueoNoEncontradoError,
    ProfesionalNoEncontradoError,
    RangoInvalidoError,
)
from app.domain.agenda import TurnoEnConflicto
from app.domain.schemas import BloqueoCreate
from app.infrastructure.models import Bloqueo, Profesional
from app.infrastructure.repositories import BaseRepository
from app.infrastructure.repositories_agenda import BloqueoRepository, TurnoRepository
from app.infrastructure.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class BloqueoDTO:
    id: uuid.UUID
    profesional_id: uuid.UUID
    desde: datetime
    hasta: datetime
    motivo: str


class _BloqueoConTurnos(Exception):
    """Señal interna: el chequeo de aplicacion vio turnos activos (no sale del modulo)."""

    def __init__(self, turnos: list[TurnoEnConflicto]) -> None:
        super().__init__("bloqueo con turnos")
        self.turnos = turnos


def _dto(bloqueo: Bloqueo) -> BloqueoDTO:
    return BloqueoDTO(
        id=bloqueo.id,
        profesional_id=bloqueo.profesional_id,
        desde=bloqueo.desde,
        hasta=bloqueo.hasta,
        motivo=bloqueo.motivo,
    )


def _en_zona(turnos: list[TurnoEnConflicto], tz: ZoneInfo) -> list[TurnoEnConflicto]:
    """Instantes con el offset de la clinica (como el resto de la API)."""
    return [
        TurnoEnConflicto(
            id=t.id, inicio=t.inicio.astimezone(tz), fin=t.fin.astimezone(tz), estado=t.estado
        )
        for t in turnos
    ]


def _releer_turnos(uow_factory: UowFactory, datos: BloqueoCreate) -> list[TurnoEnConflicto]:
    """Relectura en una UoW NUEVA (la fallida ya hizo rollback y close)."""
    with uow_factory() as session:
        return BloqueoRepository(session).turnos_activos_en_rango(
            datos.profesional_id, datos.desde, datos.hasta
        )


def crear_bloqueo(
    uow_factory: UowFactory, datos: BloqueoCreate, *, ahora: datetime, tz: ZoneInfo
) -> BloqueoDTO:
    """Alta de bloqueo. 422 si `desde < ahora`, 404 profesional, 409 si pisa turnos activos."""
    if datos.desde < ahora:
        raise RangoInvalidoError("El bloqueo no puede empezar en el pasado")
    try:
        with uow_factory() as session:
            profesional = BaseRepository(session, Profesional).get(datos.profesional_id)
            if profesional is None or not profesional.is_active:
                raise ProfesionalNoEncontradoError()
            TurnoRepository(session).bloquear_agenda(datos.profesional_id)
            bloqueos = BloqueoRepository(session)
            turnos = bloqueos.turnos_activos_en_rango(
                datos.profesional_id, datos.desde, datos.hasta
            )
            if turnos:
                raise _BloqueoConTurnos(turnos)
            bloqueo = Bloqueo(
                profesional_id=datos.profesional_id,
                desde=datos.desde,
                hasta=datos.hasta,
                motivo=datos.motivo,
            )
            bloqueos.add(bloqueo)
            session.flush()  # todo error de datos (incluido el trigger) sale antes del COMMIT
            creado = _dto(bloqueo)
    except _BloqueoConTurnos as exc:
        raise BloqueoConTurnosError(_en_zona(exc.turnos, tz)) from None
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != reservas.EXCLUSION_VIOLATION:
            raise  # otra violacion = bug (500), no se enmascara como 409
        raise BloqueoConTurnosError(_en_zona(_releer_turnos(uow_factory, datos), tz)) from exc
    return creado


def dar_de_baja_bloqueo(
    uow_factory: UowFactory, bloqueo_id: uuid.UUID, *, ahora: datetime
) -> BloqueoDTO:
    """Baja logica (`is_active=False`, `deleted_at=ahora`); 404 si no existe o ya esta de baja."""
    with uow_factory() as session:
        bloqueo = BloqueoRepository(session).obtener_activo_para_actualizar(bloqueo_id)
        if bloqueo is None:
            raise BloqueoNoEncontradoError()
        bloqueo.is_active = False
        bloqueo.deleted_at = ahora
        session.flush()
        return _dto(bloqueo)
