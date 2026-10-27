"""Caso de uso: consulta de disponibilidad (C-04). Orquesta repos + dominio puro."""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.exceptions import (
    ProfesionalNoEncontradoError,
    RangoInvalidoError,
    TratamientoNoEncontradoError,
)
from app.domain.disponibilidad import Hueco, calcular_huecos
from app.infrastructure.models import Profesional, Tratamiento
from app.infrastructure.repositories import BaseRepository
from app.infrastructure.repositories_agenda import (
    BloqueoRepository,
    HorarioRepository,
    TurnoRepository,
)


def _dias(desde: date, hasta: date, max_dias: int) -> list[date]:
    if hasta < desde:
        raise RangoInvalidoError("`hasta` no puede ser anterior a `desde`")
    cantidad = (hasta - desde).days + 1  # rango inclusivo
    if cantidad > max_dias:
        raise RangoInvalidoError(f"el rango no puede superar {max_dias} días")
    return [desde + timedelta(days=i) for i in range(cantidad)]


def consultar_disponibilidad(
    session: Session,
    *,
    profesional_id: uuid.UUID,
    desde: date,
    hasta: date,
    tratamiento_id: int | None,
    ahora: datetime,
    tz: ZoneInfo,
    max_dias: int,
) -> list[Hueco]:
    dias = _dias(desde, hasta, max_dias)

    profesional = BaseRepository(session, Profesional).get(profesional_id)
    if profesional is None or not profesional.is_active:
        raise ProfesionalNoEncontradoError()

    duracion_min = profesional.slot_default_min
    if tratamiento_id is not None:
        tratamiento = BaseRepository(session, Tratamiento).get(tratamiento_id)
        if tratamiento is None or not tratamiento.is_active:
            raise TratamientoNoEncontradoError()
        duracion_min = tratamiento.duracion_min

    # Rango [00:00 local de `desde`, 00:00 local del día siguiente a `hasta`).
    inicio_rango = datetime.combine(dias[0], time.min, tzinfo=tz)
    fin_rango = datetime.combine(dias[-1] + timedelta(days=1), time.min, tzinfo=tz)

    franjas = HorarioRepository(session).activas_por_profesional(profesional_id)
    ocupados = TurnoRepository(session).ocupados_en_rango(
        profesional_id, inicio_rango, fin_rango
    ) + BloqueoRepository(session).ocupados_en_rango(profesional_id, inicio_rango, fin_rango)

    return calcular_huecos(
        dias, franjas, profesional.slot_default_min, duracion_min, ocupados, ahora, tz
    )
