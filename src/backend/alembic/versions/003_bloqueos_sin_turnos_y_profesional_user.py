"""003: vinculo profesional<->usuario y anti-solape turno<->bloqueo (C-06).

Escrita a mano como diff revisable. Dos cambios:

1. `profesionales.user_id` (nullable, FK `users` ON DELETE RESTRICT, indice unico: NULLs
   repetidos permitidos): vincula un usuario odontologo con su profesional (DD-09).
2. Invariante "ningun turno activo (`reservado`/`confirmado`) dentro de un bloqueo activo"
   garantizado por la base (DD-08). Una EXCLUDE no cruza tablas, asi que son dos triggers
   `BEFORE ... FOR EACH ROW` con funciones PL/pgSQL:
     * `turnos`: INSERT / UPDATE OF inicio, fin, profesional_id -> `turno_sin_bloqueo()`.
     * `bloqueos`: INSERT / UPDATE OF desde, hasta, is_active, profesional_id con
       `WHEN (NEW.is_active)` -> `bloqueo_sin_turnos()`.
   Ambos rechazan con sqlstate 23P01 (`exclusion_violation`), que `reservar_turno` y
   `gestion_turnos` ya mapean a 409. Un `UPDATE` solo de `estado` (cancelar, atender) no
   dispara el trigger de turnos; dar de baja un bloqueo tampoco (`NEW.is_active` falso).

Serializacion: ambas funciones toman `pg_advisory_xact_lock(hashtext(profesional_id::text))`
ANTES de chequear, la MISMA clave que `TurnoRepository.bloquear_agenda` (`str(uuid)` de
Python == `uuid::text` de Postgres), reentrante dentro de la transaccion. Son `VOLATILE`
a proposito: cada sentencia de una funcion VOLATILE toma un snapshot nuevo, asi que el
segundo escritor, tras esperar el lock, VE la fila ya confirmada del primero (en READ
COMMITTED). Con STABLE/IMMUTABLE el chequeo seria ciego a esa fila y la carrera reaparece.
Orden global de locks: advisory -> row lock (sin deadlocks nuevos).

Verificacion previa: si ya existen pares turno activo <-> bloqueo activo superpuestos, el
upgrade ABORTA (nunca se "arreglan" datos solos; el operador decide). Es transaccional:
no queda nada a medias. `downgrade` borra triggers, funciones, indice y columna sin tocar
filas de `turnos` ni `bloqueos`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE n integer;
        BEGIN
            SELECT count(*) INTO n
            FROM turnos t
            JOIN bloqueos b ON b.profesional_id = t.profesional_id
            WHERE b.is_active
              AND t.estado IN ('reservado', 'confirmado')
              AND t.inicio < b.hasta
              AND t.fin > b.desde;
            IF n > 0 THEN
                RAISE EXCEPTION
                    '003 abortada: % par(es) turno activo <-> bloqueo activo superpuestos; '
                    'resolverlos (reprogramar/cancelar turnos o dar de baja bloqueos) y reintentar', n;
            END IF;
        END;
        $$
        """
    )
    op.add_column(
        "profesionales",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_profesionales_user_id"),
            nullable=True,
        ),
    )
    op.create_index("uq_profesionales_user_id", "profesionales", ["user_id"], unique=True)

    op.execute(
        """
        CREATE FUNCTION turno_sin_bloqueo() RETURNS trigger
        LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext(NEW.profesional_id::text));
            IF EXISTS (
                SELECT 1 FROM bloqueos b
                WHERE b.profesional_id = NEW.profesional_id
                  AND b.is_active
                  AND b.desde < NEW.fin
                  AND b.hasta > NEW.inicio
            ) THEN
                RAISE EXCEPTION 'turno dentro de un bloqueo activo del profesional'
                    USING ERRCODE = 'exclusion_violation',
                          CONSTRAINT = 'tg_turnos_sin_bloqueo';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER tg_turnos_sin_bloqueo_ins BEFORE INSERT ON turnos "
        "FOR EACH ROW WHEN (NEW.estado IN ('reservado', 'confirmado')) "
        "EXECUTE FUNCTION turno_sin_bloqueo()"
    )
    op.execute(
        "CREATE TRIGGER tg_turnos_sin_bloqueo_upd "
        "BEFORE UPDATE OF inicio, fin, profesional_id ON turnos "
        "FOR EACH ROW WHEN (NEW.estado IN ('reservado', 'confirmado')) "
        "EXECUTE FUNCTION turno_sin_bloqueo()"
    )

    op.execute(
        """
        CREATE FUNCTION bloqueo_sin_turnos() RETURNS trigger
        LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext(NEW.profesional_id::text));
            IF EXISTS (
                SELECT 1 FROM turnos t
                WHERE t.profesional_id = NEW.profesional_id
                  AND t.estado IN ('reservado', 'confirmado')
                  AND t.inicio < NEW.hasta
                  AND t.fin > NEW.desde
            ) THEN
                RAISE EXCEPTION 'bloqueo sobre turnos activos del profesional'
                    USING ERRCODE = 'exclusion_violation',
                          CONSTRAINT = 'tg_bloqueos_sin_turnos';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER tg_bloqueos_sin_turnos "
        "BEFORE INSERT OR UPDATE OF desde, hasta, is_active, profesional_id ON bloqueos "
        "FOR EACH ROW WHEN (NEW.is_active) EXECUTE FUNCTION bloqueo_sin_turnos()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tg_bloqueos_sin_turnos ON bloqueos")
    op.execute("DROP FUNCTION IF EXISTS bloqueo_sin_turnos()")
    op.execute("DROP TRIGGER IF EXISTS tg_turnos_sin_bloqueo_upd ON turnos")
    op.execute("DROP TRIGGER IF EXISTS tg_turnos_sin_bloqueo_ins ON turnos")
    op.execute("DROP FUNCTION IF EXISTS turno_sin_bloqueo()")
    op.drop_index("uq_profesionales_user_id", table_name="profesionales")
    op.drop_column("profesionales", "user_id")
