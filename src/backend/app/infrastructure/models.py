"""Modelos SQLAlchemy core (C-02).

PKs según KB 04: UUID con default app-side (`uuid4`, sin pgcrypto) salvo
`Tratamiento.id` (entero identity). `activo` ≡ `AuditMixin.is_active`
(propiedad de dominio, cero columnas duplicadas). Todo `def` sincrónico.
"""

import enum
import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.db import Base
from app.domain.base import AuditMixin
from app.domain.phone import E164_PATTERN
from app.domain.turno_estados import EstadoTurno


class UserRole(str, enum.Enum):
    SECRETARIA = "secretaria"
    ODONTOLOGO = "odontologo"


class User(Base, AuditMixin):
    """Staff con login (secretaria/odontologo). Sin rol paciente (DD-03)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # values_callable: persiste member.value ("secretaria"), igual que el
    # enum creado por la migración 001 (por defecto SQLA usaría .name).
    rol: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    @validates("email")
    def _lower_email(self, _key: str, value: str) -> str:
        return value.lower()


class Profesional(Base, AuditMixin):
    __tablename__ = "profesionales"
    __table_args__ = (
        CheckConstraint("slot_default_min > 0", name="ck_profesionales_slot_default_min_pos"),
        Index("ix_profesionales_especialidad", "especialidad"),
        # C-06 (003): un usuario odontologo <-> un profesional; NULLs repetidos permitidos.
        Index("uq_profesionales_user_id", "user_id", unique=True),
        Index(
            "ix_profesionales_activos",
            "id",
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    matricula: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    especialidad: Mapped[str | None] = mapped_column(String(120), nullable=True)
    slot_default_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_profesionales_user_id"),
        nullable=True,
    )

    @property
    def activo(self) -> bool:
        return self.is_active

    @activo.setter
    def activo(self, value: bool) -> None:
        self.is_active = value


class Paciente(Base, AuditMixin):
    __tablename__ = "pacientes"
    __table_args__ = (
        CheckConstraint(
            f"telefono ~ '{E164_PATTERN}'",
            name="ck_pacientes_telefono_e164",
        ),
        # Índice NO único: deduplicación diferida a C-05/C-11 (DD-03).
        Index("ix_pacientes_telefono", "telefono"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    telefono: Mapped[str] = mapped_column(String(16), nullable=False)
    dni: Mapped[str | None] = mapped_column(String(16), nullable=True)


class Tratamiento(Base, AuditMixin):
    __tablename__ = "tratamientos"
    __table_args__ = (
        CheckConstraint("duracion_min > 0", name="ck_tratamientos_duracion_min_pos"),
        Index(
            "ix_tratamientos_activos",
            "id",
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    duracion_min: Mapped[int] = mapped_column(Integer, nullable=False)

    @property
    def activo(self) -> bool:
        return self.is_active

    @activo.setter
    def activo(self, value: bool) -> None:
        self.is_active = value


# --- C-04: agenda (espejo de la migracion 002) -------------------------------
#
# Las exclusion constraints (`ex_turnos_sin_solape`, `ex_horario_sin_solape`),
# el tipo `timerange` y el trigger append-only de `auditoria_turno` viven SOLO
# en la migracion 002 (requieren btree_gist/tipos propios; la fuente de verdad
# del esquema es Alembic, nunca metadata.create).


class TurnoOrigen(str, enum.Enum):
    ONLINE = "online"
    SECRETARIA = "secretaria"


class AuditoriaActor(str, enum.Enum):
    PACIENTE = "paciente"
    SECRETARIA = "secretaria"
    ODONTOLOGO = "odontologo"
    SISTEMA = "sistema"


def _values(e: type[enum.Enum]) -> list[str]:
    return [m.value for m in e]


class HorarioProfesional(Base, AuditMixin):
    """Franja semanal recurrente (hora local de la clinica, sin zona)."""

    __tablename__ = "horario_profesional"
    __table_args__ = (
        CheckConstraint("dia_semana BETWEEN 0 AND 6", name="ck_horario_dia_semana_0_6"),
        CheckConstraint("hora_fin > hora_inicio", name="ck_horario_hora_fin_gt_inicio"),
        Index(
            "ix_horario_profesional_activos",
            "profesional_id",
            "dia_semana",
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profesional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profesionales.id", ondelete="RESTRICT"), nullable=False
    )
    dia_semana: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hora_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[time] = mapped_column(Time, nullable=False)


class Bloqueo(Base, AuditMixin):
    __tablename__ = "bloqueos"
    __table_args__ = (
        CheckConstraint("hasta > desde", name="ck_bloqueos_hasta_gt_desde"),
        Index(
            "ix_bloqueos_profesional_desde_activos",
            "profesional_id",
            "desde",
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profesional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profesionales.id", ondelete="RESTRICT"), nullable=False
    )
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    motivo: Mapped[str] = mapped_column(String(200), nullable=False)


class Turno(Base):
    """Sin AuditMixin: la baja es `estado=cancelado` (no `is_active`)."""

    __tablename__ = "turnos"
    __table_args__ = (
        CheckConstraint("fin > inicio", name="ck_turnos_fin_gt_inicio"),
        Index("ix_turnos_profesional_inicio", "profesional_id", "inicio"),
        Index("ix_turnos_estado", "estado"),
        Index("ix_turnos_paciente", "paciente_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profesional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profesionales.id", ondelete="RESTRICT"), nullable=False
    )
    paciente_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pacientes.id", ondelete="RESTRICT"), nullable=False
    )
    tratamiento_id: Mapped[int | None] = mapped_column(
        ForeignKey("tratamientos.id", ondelete="RESTRICT"), nullable=True
    )
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fin: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado: Mapped[EstadoTurno] = mapped_column(
        Enum(EstadoTurno, name="turno_estado", values_callable=_values),
        nullable=False,
        default=EstadoTurno.RESERVADO,
        server_default=text("'reservado'"),
    )
    origen: Mapped[TurnoOrigen] = mapped_column(
        Enum(TurnoOrigen, name="turno_origen", values_callable=_values), nullable=False
    )
    sobreturno: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    token_publico: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AuditoriaTurno(Base):
    """Append-only (trigger en la migracion 002). Solo `created_at`."""

    __tablename__ = "auditoria_turno"
    __table_args__ = (Index("ix_auditoria_turno_turno_created", "turno_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    turno_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False
    )
    accion: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_tipo: Mapped[AuditoriaActor] = mapped_column(
        Enum(AuditoriaActor, name="auditoria_actor", values_callable=_values), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    detalle: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
