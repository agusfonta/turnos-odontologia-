"""Rango de agenda (C-06 D6). Dominio puro: zona horaria inyectada, sin I/O."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.domain.turno_estados import EstadoTurno

Vista = Literal["dia", "semana"]


@dataclass(frozen=True, slots=True)
class TurnoEnConflicto:
    """Turno activo que impide un bloqueo (sin datos de paciente ni token)."""

    id: uuid.UUID
    inicio: datetime
    fin: datetime
    estado: EstadoTurno


@dataclass(frozen=True, slots=True)
class AgendaTurno:
    """Fila de la agenda interna: turno + paciente + tratamiento (sin `token_publico`)."""

    id: uuid.UUID
    inicio: datetime
    fin: datetime
    estado: EstadoTurno
    origen: str
    sobreturno: bool
    paciente_id: uuid.UUID
    paciente_nombre: str
    paciente_telefono: str
    tratamiento_id: int | None
    tratamiento_nombre: str | None


def rango_agenda(dia: date, vista: Vista) -> tuple[date, date]:
    """Fechas locales `(desde, hasta)` inclusivas: el dia, o lunes..domingo de su semana ISO."""
    if vista == "dia":
        return dia, dia
    if vista == "semana":
        lunes = dia - timedelta(days=dia.weekday())
        return lunes, lunes + timedelta(days=6)
    raise ValueError(f"vista invalida: {vista!r}")


def limites_instantes(desde: date, hasta: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """`[desde 00:00 local, (hasta + 1 dia) 00:00 local)`; el offset sigue al DST de `tz`."""
    return (
        datetime.combine(desde, time.min, tzinfo=tz),
        datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=tz),
    )
