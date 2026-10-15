"""Modelos SQLAlchemy core (C-02).

PKs según KB 04: UUID con default app-side (`uuid4`, sin pgcrypto) salvo
`Tratamiento.id` (entero identity). `activo` ≡ `AuditMixin.is_active`
(propiedad de dominio, cero columnas duplicadas). Todo `def` sincrónico.
"""

import enum
import uuid

from sqlalchemy import CheckConstraint, Enum, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.db import Base
from app.domain.base import AuditMixin
from app.domain.phone import E164_PATTERN


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
