"""002: turnos, bloqueos, auditoria_turno y horario_profesional (C-04).

Escrita a mano como diff revisable (sin autogenerate ni creacion por metadata).
Invariantes en la DB (regla dura: anti-solape nunca solo en la app):
  * `ex_turnos_sin_solape`: exclusion gist sobre (profesional, tstzrange [)),
    solo turnos no cancelados y no sobreturno.
  * `ex_horario_sin_solape`: exclusion gist sobre (profesional, dia, timerange [))
    solo franjas activas. Postgres no trae rango de `time`: se crea `timerange`.
  * `auditoria_turno` append-only por triggers (UPDATE/DELETE por fila, TRUNCATE por sentencia).
`btree_gist` es "trusted" (PG >= 13): la crea cualquier rol con CREATE sobre la
DB; si el rol de deploy no puede, pre-crearla como DBA. El downgrade NO borra
la extension (puede ser compartida) pero si el tipo `timerange`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TURNO_ESTADO_VALUES = ("reservado", "confirmado", "cancelado", "ausente", "atendido")
TURNO_ORIGEN_VALUES = ("online", "secretaria")
AUDITORIA_ACTOR_VALUES = ("paciente", "secretaria", "odontologo", "sistema")


def _ts(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _audit_columns() -> list[sa.Column]:
    """Mismas columnas que `AuditMixin` (001); usado por bloqueos y horarios."""
    return [
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _fk(name: str, target: str, *, nullable: bool = False, type_=None) -> sa.Column:
    return sa.Column(
        name,
        type_ or postgresql.UUID(as_uuid=True),
        sa.ForeignKey(target, ondelete="RESTRICT"),
        nullable=nullable,
    )


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE TYPE timerange AS RANGE (subtype = time)")

    # create_type=False: las columnas referencian el tipo sin re-emitir CREATE TYPE.
    turno_estado = postgresql.ENUM(*TURNO_ESTADO_VALUES, name="turno_estado", create_type=False)
    turno_origen = postgresql.ENUM(*TURNO_ORIGEN_VALUES, name="turno_origen", create_type=False)
    auditoria_actor = postgresql.ENUM(
        *AUDITORIA_ACTOR_VALUES, name="auditoria_actor", create_type=False
    )
    for enum in (turno_estado, turno_origen, auditoria_actor):
        enum.create(bind, checkfirst=True)

    # --- horario_profesional (franjas semanales, hora local de la clinica) ---
    op.create_table(
        "horario_profesional",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _fk("profesional_id", "profesionales.id"),
        sa.Column("dia_semana", sa.SmallInteger(), nullable=False),
        sa.Column("hora_inicio", sa.Time(), nullable=False),
        sa.Column("hora_fin", sa.Time(), nullable=False),
        sa.CheckConstraint("dia_semana BETWEEN 0 AND 6", name="ck_horario_dia_semana_0_6"),
        sa.CheckConstraint("hora_fin > hora_inicio", name="ck_horario_hora_fin_gt_inicio"),
        *_audit_columns(),
    )
    op.execute(
        "ALTER TABLE horario_profesional ADD CONSTRAINT ex_horario_sin_solape "
        "EXCLUDE USING gist (profesional_id WITH =, dia_semana WITH =, "
        "timerange(hora_inicio, hora_fin, '[)') WITH &&) WHERE (is_active)"
    )
    op.create_index(
        "ix_horario_profesional_activos",
        "horario_profesional",
        ["profesional_id", "dia_semana"],
        postgresql_where=sa.text("is_active"),
    )

    # --- bloqueos ---
    op.create_table(
        "bloqueos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _fk("profesional_id", "profesionales.id"),
        sa.Column("desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hasta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motivo", sa.String(200), nullable=False),
        sa.CheckConstraint("hasta > desde", name="ck_bloqueos_hasta_gt_desde"),
        *_audit_columns(),
    )
    op.create_index(
        "ix_bloqueos_profesional_desde_activos",
        "bloqueos",
        ["profesional_id", "desde"],
        postgresql_where=sa.text("is_active"),
    )

    # --- turnos (sin AuditMixin: la baja es estado=cancelado) ---
    op.create_table(
        "turnos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _fk("profesional_id", "profesionales.id"),
        _fk("paciente_id", "pacientes.id"),
        _fk("tratamiento_id", "tratamientos.id", nullable=True, type_=sa.Integer()),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", turno_estado, server_default=sa.text("'reservado'"), nullable=False),
        sa.Column("origen", turno_origen, nullable=False),
        sa.Column("sobreturno", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("token_publico", sa.String(64), nullable=True, unique=True),
        _fk("created_by", "users.id", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("fin > inicio", name="ck_turnos_fin_gt_inicio"),
    )
    op.execute(
        "ALTER TABLE turnos ADD CONSTRAINT ex_turnos_sin_solape "
        "EXCLUDE USING gist (profesional_id WITH =, tstzrange(inicio, fin, '[)') WITH &&) "
        "WHERE (estado <> 'cancelado' AND NOT sobreturno)"
    )
    op.create_index("ix_turnos_profesional_inicio", "turnos", ["profesional_id", "inicio"])
    op.create_index("ix_turnos_estado", "turnos", ["estado"])
    op.create_index("ix_turnos_paciente", "turnos", ["paciente_id"])

    # --- auditoria_turno (append-only) ---
    op.create_table(
        "auditoria_turno",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _fk("turno_id", "turnos.id"),
        sa.Column("accion", sa.String(32), nullable=False),
        sa.Column("actor_tipo", auditoria_actor, nullable=False),
        _fk("actor_user_id", "users.id", nullable=True),
        sa.Column(
            "detalle", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        _ts("created_at"),
    )
    op.create_index(
        "ix_auditoria_turno_turno_created", "auditoria_turno", ["turno_id", "created_at"]
    )
    op.execute(
        """
        CREATE FUNCTION auditoria_turno_inmutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'auditoria_turno es append-only: % prohibido', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_auditoria_turno_inmutable "
        "BEFORE UPDATE OR DELETE ON auditoria_turno "
        "FOR EACH ROW EXECUTE FUNCTION auditoria_turno_inmutable()"
    )
    # TRUNCATE no dispara triggers por fila: guard a nivel sentencia (TG_OP='TRUNCATE').
    op.execute(
        "CREATE TRIGGER trg_auditoria_turno_sin_truncate "
        "BEFORE TRUNCATE ON auditoria_turno "
        "FOR EACH STATEMENT EXECUTE FUNCTION auditoria_turno_inmutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_auditoria_turno_sin_truncate ON auditoria_turno")
    op.execute("DROP TRIGGER IF EXISTS trg_auditoria_turno_inmutable ON auditoria_turno")
    op.execute("DROP FUNCTION IF EXISTS auditoria_turno_inmutable()")
    # Orden inverso de FKs; indices y exclusions caen con su tabla.
    op.drop_table("auditoria_turno")
    op.drop_table("turnos")
    op.drop_table("bloqueos")
    op.drop_table("horario_profesional")
    bind = op.get_bind()
    for name in ("auditoria_actor", "turno_origen", "turno_estado"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
    op.execute("DROP TYPE IF EXISTS timerange")
    # btree_gist NO se elimina (puede ser compartida).
