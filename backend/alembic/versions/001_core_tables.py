"""001: tablas core (users, profesionales, pacientes, tratamientos).

Escrita a mano como diff revisable (sin autogenerate). Enum `user_role`
staff-only (sin `paciente`, DD-03). `activo` ≡ `is_active` (sin columna
duplicada) con índices parciales WHERE is_active. UUIDs con default
app-side (sin pgcrypto). Downgrade completo en orden inverso.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLE_VALUES = ("secretaria", "odontologo")
E164_REGEX = r"^\+[1-9][0-9]{7,14}$"


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    # create_type=False: la columna lo referencia sin re-emitir CREATE TYPE.
    user_role = postgresql.ENUM(*USER_ROLE_VALUES, name="user_role", create_type=False)
    user_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("rol", user_role, nullable=False),
        *_audit_columns(),
    )
    op.create_table(
        "profesionales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("matricula", sa.String(50), nullable=False, unique=True),
        sa.Column("especialidad", sa.String(120), nullable=True),
        sa.Column(
            "slot_default_min",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.CheckConstraint("slot_default_min > 0", name="ck_profesionales_slot_default_min_pos"),
        *_audit_columns(),
    )
    op.create_index(
        "ix_profesionales_especialidad", "profesionales", ["especialidad"]
    )
    op.create_index(
        "ix_profesionales_activos",
        "profesionales",
        ["id"],
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_table(
        "pacientes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("telefono", sa.String(16), nullable=False),
        sa.Column("dni", sa.String(16), nullable=True),
        sa.CheckConstraint(f"telefono ~ '{E164_REGEX}'", name="ck_pacientes_telefono_e164"),
        *_audit_columns(),
    )
    # Índice NO único: deduplicación diferida a C-05/C-11 (DD-03).
    op.create_index("ix_pacientes_telefono", "pacientes", ["telefono"])
    op.create_table(
        "tratamientos",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("nombre", sa.String(120), nullable=False, unique=True),
        sa.Column("duracion_min", sa.Integer(), nullable=False),
        sa.CheckConstraint("duracion_min > 0", name="ck_tratamientos_duracion_min_pos"),
        *_audit_columns(),
    )
    op.create_index(
        "ix_tratamientos_activos",
        "tratamientos",
        ["id"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_tratamientos_activos", table_name="tratamientos")
    op.drop_table("tratamientos")
    op.drop_index("ix_pacientes_telefono", table_name="pacientes")
    op.drop_table("pacientes")
    op.drop_index("ix_profesionales_activos", table_name="profesionales")
    op.drop_index("ix_profesionales_especialidad", table_name="profesionales")
    op.drop_table("profesionales")
    op.drop_table("users")
    postgresql.ENUM(*USER_ROLE_VALUES, name="user_role").drop(op.get_bind(), checkfirst=True)
