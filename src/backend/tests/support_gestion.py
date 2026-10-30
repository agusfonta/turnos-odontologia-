"""Helpers compartidos de los tests de gestion de secretaria (C-05). Solo datos sinteticos."""

import uuid
from datetime import datetime, time, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import (
    AuditoriaTurno,
    HorarioProfesional,
    Paciente,
    Profesional,
    Turno,
    TurnoOrigen,
    User,
    UserRole,
)

AHORA = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
LUNES = "2030-03-04"  # weekday() == 0
OFFSET = "-03:00"


def crear_profesional(session: Session, slot: int = 30) -> Profesional:
    prof = Profesional(
        nombre="Dra. Sintetica", matricula=f"MAT-{uuid.uuid4().hex[:8]}", slot_default_min=slot
    )
    session.add(prof)
    session.flush()
    session.add(
        HorarioProfesional(profesional_id=prof.id, dia_semana=0, hora_inicio=time(9), hora_fin=time(18))
    )
    session.commit()
    return prof


def crear_secretaria(session: Session) -> User:
    user = User(
        email=f"secretaria-{uuid.uuid4().hex[:6]}@example.test",
        password_hash="x",
        rol=UserRole.SECRETARIA,
    )
    session.add(user)
    session.commit()
    return user


def inicio(hhmm: str, dia: str = LUNES) -> datetime:
    return datetime.fromisoformat(f"{dia}T{hhmm}:00{OFFSET}")


def crear_turno(
    session: Session,
    prof: Profesional,
    hhmm: str = "10:00",
    *,
    minutos: int = 30,
    estado: EstadoTurno = EstadoTurno.RESERVADO,
    sobreturno: bool = False,
    telefono: str = "+5491100000099",
    dia: str = LUNES,
) -> Turno:
    paciente = Paciente(nombre="Paciente Previo", telefono=telefono)
    session.add(paciente)
    session.flush()
    ini = inicio(hhmm, dia)
    turno = Turno(
        profesional_id=prof.id,
        paciente_id=paciente.id,
        inicio=ini,
        fin=ini + timedelta(minutes=minutos),
        estado=estado,
        origen=TurnoOrigen.ONLINE,
        sobreturno=sobreturno,
        token_publico=uuid.uuid4().hex,
    )
    session.add(turno)
    session.commit()
    return turno


def cuenta(session: Session, modelo) -> int:
    session.expire_all()
    return session.scalar(sa.select(sa.func.count()).select_from(modelo))


def auditorias(session: Session, turno_id: uuid.UUID, accion: str | None = None) -> list[AuditoriaTurno]:
    session.expire_all()
    stmt = sa.select(AuditoriaTurno).where(AuditoriaTurno.turno_id == turno_id)
    if accion:
        stmt = stmt.where(AuditoriaTurno.accion == accion)
    return list(session.scalars(stmt.order_by(AuditoriaTurno.created_at)))
