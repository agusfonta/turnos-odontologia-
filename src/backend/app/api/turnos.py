"""Turnos: reserva (C-04, C-04b) y gestion de secretaria (C-05).

* `POST /api/turnos`: reserva publica o de secretaria (sin tocar, `reservar_turno`).
* `POST /api/turnos/manual`: alta manual (reusa paciente por telefono, admite sobreturno).
* `PATCH /api/turnos/{id}`: reprograma (confirmado -> reservado); re-encola el recordatorio.
* `DELETE /api/turnos/{id}`: cancela (baja logica); quita el recordatorio de la cola.
* `POST /api/turnos/{id}/confirmar`: confirma (C-07; mismo caso de uso que la puerta por token,
  con actor `secretaria`); idempotente, no toca la cola.
Las rutas de gestion exigen rol `secretaria` (401 sin token/invalido, 403 otro rol). La puerta
publica por token vive en `app/api/autogestion.py`.

Patron de efectos post-commit: el caso de uso es el limite de la transaccion (si
retorna, ya hubo commit); los efectos externos (Redis) se ejecutan aca, DESPUES de que
retorno, con el DTO. Cualquier excepcion del caso de uso sale antes del efecto, asi que
nunca se encola/desencola sin commit. Ningun efecto envia WhatsApp: solo la cola.
Todo `def` (las llamadas a la DB son bloqueantes).
"""

import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import get_optional_staff, require_secretaria
from app.application.gestion_turnos import (
    Actor,
    TurnoGestionado,
    alta_manual_turno,
    cancelar_turno,
    confirmar_turno,
    reprogramar_turno,
)
from app.application.reservas import reservar_turno
from app.core.clock import get_ahora
from app.core.settings import get_settings
from app.domain.schemas import (
    TurnoCreado,
    TurnoCreate,
    TurnoGestionadoOut,
    TurnoManualCreado,
    TurnoManualCreate,
    TurnoReprogramar,
)
from app.infrastructure.jobs import RecordatorioQueue, get_recordatorio_queue
from app.infrastructure.models import AuditoriaActor, User
from app.infrastructure.unit_of_work import UowFactory, get_uow_factory

router = APIRouter(prefix="/turnos", tags=["turnos"])

UowDep = Annotated[UowFactory, Depends(get_uow_factory)]
AhoraDep = Annotated[datetime, Depends(get_ahora)]
StaffDep = Annotated[User | None, Depends(get_optional_staff)]
ColaDep = Annotated[RecordatorioQueue, Depends(get_recordatorio_queue)]
SecretariaDep = Annotated[User, Depends(require_secretaria)]
TurnoIdPath = Annotated[uuid.UUID, Path()]


@router.post("", response_model=TurnoCreado, status_code=status.HTTP_201_CREATED)
def crear_turno(
    datos: TurnoCreate, uow_factory: UowDep, ahora: AhoraDep, staff: StaffDep, cola: ColaDep
) -> TurnoCreado:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    reservado = reservar_turno(
        uow_factory, datos, staff_id=staff.id if staff else None, ahora=ahora, tz=tz
    )  # el commit ocurre dentro de la UoW del caso de uso
    cola.encolar(reservado.id, reservado.inicio)  # post-commit; nunca lanza
    return TurnoCreado(
        id=reservado.id,
        profesional_id=reservado.profesional_id,
        tratamiento_id=reservado.tratamiento_id,
        inicio=reservado.inicio.astimezone(tz),
        fin=reservado.fin.astimezone(tz),
        estado="reservado",
        origen=reservado.origen,
        token_publico=reservado.token_publico,
    )


@router.post("/manual", response_model=TurnoManualCreado, status_code=status.HTTP_201_CREATED)
def alta_manual(
    datos: TurnoManualCreate,
    uow_factory: UowDep,
    ahora: AhoraDep,
    secretaria: SecretariaDep,
    cola: ColaDep,
) -> TurnoManualCreado:
    """Alta por secretaria. Declarada antes de `/{turno_id}` (no colisionan por metodo)."""
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    creado = alta_manual_turno(uow_factory, datos, staff_id=secretaria.id, ahora=ahora, tz=tz)
    cola.encolar(creado.id, creado.inicio)  # post-commit; nunca lanza
    return TurnoManualCreado(
        id=creado.id,
        profesional_id=creado.profesional_id,
        paciente_id=creado.paciente_id,
        tratamiento_id=creado.tratamiento_id,
        inicio=creado.inicio.astimezone(tz),
        fin=creado.fin.astimezone(tz),
        estado="reservado",
        origen=creado.origen,
        sobreturno=creado.sobreturno,
        token_publico=creado.token_publico,
    )


def _gestionado_out(dto: TurnoGestionado, tz: ZoneInfo) -> TurnoGestionadoOut:
    return TurnoGestionadoOut(
        id=dto.id,
        profesional_id=dto.profesional_id,
        paciente_id=dto.paciente_id,
        tratamiento_id=dto.tratamiento_id,
        inicio=dto.inicio.astimezone(tz),
        fin=dto.fin.astimezone(tz),
        estado=dto.estado.value,
        origen=dto.origen,
        sobreturno=dto.sobreturno,
    )


@router.patch("/{turno_id}", response_model=TurnoGestionadoOut)
def reprogramar(
    turno_id: TurnoIdPath,
    datos: TurnoReprogramar,
    uow_factory: UowDep,
    ahora: AhoraDep,
    secretaria: SecretariaDep,
    cola: ColaDep,
) -> TurnoGestionadoOut:
    """Reprograma al nuevo `inicio`; `confirmado` vuelve a `reservado` (DD-07)."""
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    actor = Actor(AuditoriaActor.SECRETARIA, secretaria.id)
    dto = reprogramar_turno(uow_factory, turno_id, datos, actor=actor, ahora=ahora, tz=tz)
    cola.encolar(dto.id, dto.inicio)  # post-commit; ZADD actualiza el score del miembro
    return _gestionado_out(dto, tz)


@router.delete("/{turno_id}", response_model=TurnoGestionadoOut)
def cancelar(
    turno_id: TurnoIdPath,
    uow_factory: UowDep,
    ahora: AhoraDep,
    secretaria: SecretariaDep,
    cola: ColaDep,
) -> TurnoGestionadoOut:
    """Baja logica del turno (200 con el turno cancelado); quita su recordatorio."""
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    actor = Actor(AuditoriaActor.SECRETARIA, secretaria.id)
    dto = cancelar_turno(uow_factory, turno_id, actor=actor, ahora=ahora)
    cola.cancelar(dto.id)  # post-commit; nunca lanza
    return _gestionado_out(dto, tz)


@router.post("/{turno_id}/confirmar", response_model=TurnoGestionadoOut)
def confirmar(
    turno_id: TurnoIdPath,
    uow_factory: UowDep,
    ahora: AhoraDep,
    secretaria: SecretariaDep,
) -> TurnoGestionadoOut:
    """`reservado` -> `confirmado`; reconfirmar es 200 sin auditoria; no toca la cola."""
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    actor = Actor(AuditoriaActor.SECRETARIA, secretaria.id)
    dto = confirmar_turno(uow_factory, turno_id, actor=actor, ahora=ahora)
    return _gestionado_out(dto, tz)
