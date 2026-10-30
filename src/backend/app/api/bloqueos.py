"""Bloqueos de agenda (C-06): alta y baja logica por secretaria.

* `POST /api/bloqueos`: crea un bloqueo (409 `bloqueo_con_turnos` si pisa turnos activos).
* `DELETE /api/bloqueos/{id}`: baja logica (200 con el bloqueo; 404 si no existe o ya esta de baja).
Ambas exigen rol `secretaria` (401 sin token/invalido, 403 otro rol). Sin efectos post-commit
(no hay cola); la trazabilidad (DD-12) es un `logger.info` estructurado DESPUES del retorno
del caso de uso (= ya hubo commit). Todo `def` (las llamadas a la DB son bloqueantes).
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import require_secretaria
from app.application.bloqueos import BloqueoDTO, crear_bloqueo, dar_de_baja_bloqueo
from app.core.clock import get_ahora
from app.core.settings import get_settings
from app.domain.schemas import BloqueoCreate, BloqueoOut
from app.infrastructure.models import User
from app.infrastructure.unit_of_work import UowFactory, get_uow_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bloqueos", tags=["bloqueos"])

UowDep = Annotated[UowFactory, Depends(get_uow_factory)]
AhoraDep = Annotated[datetime, Depends(get_ahora)]
SecretariaDep = Annotated[User, Depends(require_secretaria)]
BloqueoIdPath = Annotated[uuid.UUID, Path()]


def _out(dto: BloqueoDTO, tz: ZoneInfo) -> BloqueoOut:
    return BloqueoOut(
        id=dto.id,
        profesional_id=dto.profesional_id,
        desde=dto.desde.astimezone(tz),
        hasta=dto.hasta.astimezone(tz),
        motivo=dto.motivo,
    )


def _registrar(accion: str, dto: BloqueoDTO, user: User) -> None:
    logger.info(
        "%s bloqueo_id=%s profesional_id=%s user_id=%s",
        accion,
        dto.id,
        dto.profesional_id,
        user.id,
        extra={
            "accion": accion,
            "bloqueo_id": dto.id,
            "profesional_id": dto.profesional_id,
            "user_id": user.id,
        },
    )


@router.post("", response_model=BloqueoOut, status_code=status.HTTP_201_CREATED)
def crear(
    datos: BloqueoCreate, uow_factory: UowDep, ahora: AhoraDep, secretaria: SecretariaDep
) -> BloqueoOut:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    dto = crear_bloqueo(uow_factory, datos, ahora=ahora, tz=tz)
    _registrar("bloqueo_creado", dto, secretaria)  # post-commit; solo si el alta tuvo exito
    return _out(dto, tz)


@router.delete("/{bloqueo_id}", response_model=BloqueoOut)
def dar_de_baja(
    bloqueo_id: BloqueoIdPath, uow_factory: UowDep, ahora: AhoraDep, secretaria: SecretariaDep
) -> BloqueoOut:
    """Baja logica: la fila se conserva inactiva con `deleted_at`; el rango vuelve a la agenda."""
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    dto = dar_de_baja_bloqueo(uow_factory, bloqueo_id, ahora=ahora)
    _registrar("bloqueo_baja", dto, secretaria)
    return _out(dto, tz)
