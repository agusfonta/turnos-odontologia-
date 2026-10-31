"""Autogestion del paciente por token (C-07): consultar, confirmar, reprogramar y cancelar.

Rutas PUBLICAS (sin `Authorization`): el secreto es el token del path.
* `GET    /api/turnos/por-token/{token}`            detalle publico (sin datos del paciente).
* `POST   /api/turnos/por-token/{token}/confirmar`  `reservado` -> `confirmado` (idempotente).
* `PATCH  /api/turnos/por-token/{token}`            reprograma (solo `inicio`; `confirmado` -> `reservado`).
* `DELETE /api/turnos/por-token/{token}`            baja logica; quita el recordatorio.

`token` es un `str` SIN restricciones de FastAPI (`min_length`/`pattern` devolverian 422 y
distinguirian tokens malformados) y se declara con el conversor `:path`: Starlette decodifica
`%2F` a `/` ANTES de rutear y, con `{token}` simple, un token con barra no matchearia ninguna
ruta y caeria al 404 generico (cuerpo distinto). Con `:path` llega a `resolver_token` igual.
El formato lo valida `resolver_token`, que responde el
MISMO 404 `turno_no_encontrado` para inexistente y malformado. Esta capa no loguea el token.
Router fino: token -> caso de uso con actor `paciente` -> efecto post-commit en Redis (el
caso de uso es el limite de la transaccion; si retorna, ya hubo commit) -> DTO a `response_model`.
Todo `def`. Se registra antes que `turnos_router` en `main.py` para dejar explicita la precedencia.
"""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path

from app.application.autogestion import (
    cancelar_por_token,
    confirmar_por_token,
    consultar_por_token,
    gestionable_hasta,
    reprogramar_por_token,
)
from app.application.gestion_turnos import TurnoGestionado
from app.core.clock import get_ahora
from app.core.settings import get_settings
from app.domain.schemas import TurnoPorTokenDetalle, TurnoPorTokenOut, TurnoReprogramarPublico
from app.infrastructure.jobs import RecordatorioQueue, get_recordatorio_queue
from app.infrastructure.unit_of_work import UowFactory, get_uow_factory

router = APIRouter(prefix="/turnos/por-token", tags=["autogestion"])

UowDep = Annotated[UowFactory, Depends(get_uow_factory)]
AhoraDep = Annotated[datetime, Depends(get_ahora)]
ColaDep = Annotated[RecordatorioQueue, Depends(get_recordatorio_queue)]
TokenPath = Annotated[str, Path()]  # sin restricciones: el 404 uniforme lo da `resolver_token`


def _out(dto: TurnoGestionado, tz: ZoneInfo) -> TurnoPorTokenOut:
    return TurnoPorTokenOut(
        inicio=dto.inicio.astimezone(tz),
        fin=dto.fin.astimezone(tz),
        estado=dto.estado.value,
        profesional_id=dto.profesional_id,
        tratamiento_id=dto.tratamiento_id,
        gestionable_hasta=gestionable_hasta(dto.inicio).astimezone(tz),
    )


@router.get("/{token:path}", response_model=TurnoPorTokenDetalle)
def obtener_por_token(token: TokenPath, uow_factory: UowDep) -> TurnoPorTokenDetalle:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    dto = consultar_por_token(uow_factory, token)
    return TurnoPorTokenDetalle(
        inicio=dto.inicio.astimezone(tz),
        fin=dto.fin.astimezone(tz),
        estado=dto.estado.value,
        profesional_id=dto.profesional_id,
        profesional_nombre=dto.profesional_nombre,
        tratamiento_id=dto.tratamiento_id,
        tratamiento_nombre=dto.tratamiento_nombre,
        gestionable_hasta=dto.gestionable_hasta.astimezone(tz),
    )


@router.post("/{token:path}/confirmar", response_model=TurnoPorTokenOut)
def confirmar(token: TokenPath, uow_factory: UowDep, ahora: AhoraDep) -> TurnoPorTokenOut:
    """Confirma la asistencia; no toca la cola (el recordatorio sigue su curso)."""
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    return _out(confirmar_por_token(uow_factory, token, ahora=ahora), tz)


@router.patch("/{token:path}", response_model=TurnoPorTokenOut)
def reprogramar(
    token: TokenPath,
    datos: TurnoReprogramarPublico,
    uow_factory: UowDep,
    ahora: AhoraDep,
    cola: ColaDep,
) -> TurnoPorTokenOut:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    dto = reprogramar_por_token(uow_factory, token, datos, ahora=ahora, tz=tz)
    cola.encolar(dto.id, dto.inicio)  # post-commit; nunca lanza
    return _out(dto, tz)


@router.delete("/{token:path}", response_model=TurnoPorTokenOut)
def cancelar(token: TokenPath, uow_factory: UowDep, ahora: AhoraDep, cola: ColaDep) -> TurnoPorTokenOut:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    dto = cancelar_por_token(uow_factory, token, ahora=ahora)
    cola.cancelar(dto.id)  # post-commit; nunca lanza
    return _out(dto, tz)
