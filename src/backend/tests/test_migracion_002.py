"""C-04 2.1: migración 002 (turnos, bloqueos, auditoria_turno, horario_profesional)."""

import sqlalchemy as sa

from tests.support import alembic, db_temporal, snapshot_esquema

TABLAS_002 = {"turnos", "bloqueos", "auditoria_turno", "horario_profesional"}


def _nombres(engine: sa.Engine, query: str) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(sa.text(query))}


def test_upgrade_crea_tablas_y_constraint():
    with db_temporal() as url:
        assert alembic(url, "upgrade", "head").returncode == 0
        engine = sa.create_engine(url)
        try:
            tablas = _nombres(engine, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
            assert TABLAS_002 <= tablas

            constraints = _nombres(engine, "SELECT conname FROM pg_constraint")
            assert {"ex_turnos_sin_solape", "ex_horario_sin_solape"} <= constraints

            tipos = _nombres(engine, "SELECT typname FROM pg_type")
            assert {"timerange", "turno_estado", "turno_origen", "auditoria_actor"} <= tipos

            triggers = _nombres(engine, "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
            assert {"trg_auditoria_turno_inmutable", "trg_auditoria_turno_sin_truncate"} <= triggers
        finally:
            engine.dispose()


def test_downgrade_001_elimina_todo_lo_de_002_y_conserva_001():
    with db_temporal() as url:
        assert alembic(url, "upgrade", "head").returncode == 0
        assert alembic(url, "downgrade", "001").returncode == 0
        engine = sa.create_engine(url)
        try:
            tablas = _nombres(engine, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
            assert not (TABLAS_002 & tablas)
            assert {"users", "profesionales", "pacientes", "tratamientos"} <= tablas

            tipos = _nombres(engine, "SELECT typname FROM pg_type")
            assert not ({"timerange", "turno_estado", "turno_origen", "auditoria_actor"} & tipos)
            funciones = _nombres(engine, "SELECT proname FROM pg_proc")
            assert "auditoria_turno_inmutable" not in funciones
        finally:
            engine.dispose()


def test_ciclo_upgrade_downgrade_upgrade_deja_esquema_identico():
    with db_temporal() as url:
        assert alembic(url, "upgrade", "head").returncode == 0
        engine = sa.create_engine(url)
        try:
            primero = snapshot_esquema(engine)
            assert any(r[0] == "turnos" for r in primero["columnas"])  # foto no vacía
            assert alembic(url, "downgrade", "001").returncode == 0
            assert alembic(url, "upgrade", "head").returncode == 0
            assert snapshot_esquema(engine) == primero
        finally:
            engine.dispose()
