"""GET /api/disponibilidad: huecos reales de un profesional (C-04, sin auth)."""

import uuid
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.application.disponibilidad import consultar_disponibilidad
from app.core.clock import get_ahora
from app.core.db import get_db
from app.core.settings import get_settings
from app.domain.disponibilidad import Hueco
from app.domain.schemas import HuecoPublico

router = APIRouter(prefix="/disponibilidad", tags=["disponibilidad"])

DbDep = Annotated[Session, Depends(get_db)]
AhoraDep = Annotated[datetime, Depends(get_ahora)]


@router.get("", response_model=list[HuecoPublico])
def obtener_disponibilidad(
    db: DbDep,
    ahora: AhoraDep,
    profesional_id: Annotated[uuid.UUID, Query()],
    desde: Annotated[date, Query(description="Fecha local de la clínica, inclusiva")],
    hasta: Annotated[date, Query(description="Fecha local de la clínica, inclusiva")],
    tratamiento_id: Annotated[int | None, Query()] = None,
) -> list[Hueco]:
    settings = get_settings()
    return consultar_disponibilidad(
        db,
        profesional_id=profesional_id,
        desde=desde,
        hasta=hasta,
        tratamiento_id=tratamiento_id,
        ahora=ahora,
        tz=ZoneInfo(settings.CLINIC_TIMEZONE),
        max_dias=settings.DISPONIBILIDAD_MAX_DIAS,
    )
