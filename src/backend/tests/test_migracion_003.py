"""C-06 2.x: migración 003 (profesionales.user_id + triggers anti-solape turno<->bloqueo).

Las pruebas de triggers insertan por SQL directo contra PG real (DB clonada en `head`):
el invariante debe sostenerse sin pasar por la capa de aplicación.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.support import alembic, db_temporal, snapshot_esquema

BASE = datetime(2030, 3, 4, 12, 0, tzinfo=timezone.utc)  # fecha sintética futura


def _h(minutos: int) -> datetime:
    return BASE + timedelta(minutes=minutos)


def _sqlstate(exc: IntegrityError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


# --- helpers SQL (todo sintético) -------------------------------------------------------


def _user(conn: sa.Connection, rol: str = "odontologo") -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash, rol) "
            "VALUES (:id, :email, 'x', CAST(:rol AS user_role))"
        ),
        {"id": uid, "email": f"u-{uid.hex[:8]}@example.test", "rol": rol},
    )
    return uid


def _profesional(conn: sa.Connection, user_id: uuid.UUID | None = None) -> uuid.UUID:
    pid = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO profesionales (id, nombre, matricula, user_id) "
            "VALUES (:id, 'Dr. Sintetico', :mat, :uid)"
        ),
        {"id": pid, "mat": f"MAT-{pid.hex[:8]}", "uid": user_id},
    )
    return pid


def _paciente(conn: sa.Connection) -> uuid.UUID:
    pid = uuid.uuid4()
    conn.execute(
        sa.text("INSERT INTO pacientes (id, nombre, telefono) VALUES (:id, 'Paciente S', '+5491100000000')"),
        {"id": pid},
    )
    return pid


def _turno(
    conn: sa.Connection,
    prof: uuid.UUID,
    pac: uuid.UUID,
    ini: int,
    fin: int,
    estado: str = "reservado",
    sobreturno: bool = False,
) -> uuid.UUID:
    tid = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO turnos (id, profesional_id, paciente_id, inicio, fin, estado, origen, sobreturno) "
            "VALUES (:id, :p, :pac, :i, :f, CAST(:e AS turno_estado), 'online', :s)"
        ),
        {"id": tid, "p": prof, "pac": pac, "i": _h(ini), "f": _h(fin), "e": estado, "s": sobreturno},
    )
    return tid


def _bloqueo(
    conn: sa.Connection, prof: uuid.UUID, desde: int, hasta: int, *, activo: bool = True
) -> uuid.UUID:
    bid = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO bloqueos (id, profesional_id, desde, hasta, motivo, is_active) "
            "VALUES (:id, :p, :d, :h, 'Motivo sintetico', :a)"
        ),
        {"id": bid, "p": prof, "d": _h(desde), "h": _h(hasta), "a": activo},
    )
    return bid


@pytest.fixture
def conn(mig_engine: sa.Engine):
    """Conexión en autocommit: cada sentencia es su propia transacción (un error no envenena la siguiente)."""
    with mig_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        yield c


# --- 2.1 profesionales.user_id -----------------------------------------------------------


def test_user_id_unico(conn):
    uid = _user(conn)
    _profesional(conn, uid)
    with pytest.raises(IntegrityError) as exc:
        _profesional(conn, uid)
    assert _sqlstate(exc.value) == "23505"


def test_profesional_sin_usuario_aceptado_y_varios_nulls(conn):
    a, b = _profesional(conn), _profesional(conn)
    filas = conn.execute(
        sa.text("SELECT count(*) FROM profesionales WHERE id IN (:a, :b) AND user_id IS NULL"),
        {"a": a, "b": b},
    ).scalar_one()
    assert filas == 2


def test_user_id_con_fk_a_usuario_inexistente_rechazado(conn):
    with pytest.raises(IntegrityError) as exc:
        _profesional(conn, uuid.uuid4())
    assert _sqlstate(exc.value) == "23503"


def test_user_id_fk_es_restrict(conn):
    uid = _user(conn)
    _profesional(conn, uid)
    with pytest.raises(IntegrityError) as exc:
        conn.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": uid})
    assert _sqlstate(exc.value) == "23503"


# --- 2.2 trigger turnos -> bloqueos ------------------------------------------------------


@pytest.fixture
def ctx(conn):
    prof, otro = _profesional(conn), _profesional(conn)
    return conn, prof, otro, _paciente(conn)


def test_insert_turno_dentro_de_bloqueo_rechazado(ctx):
    conn, prof, _otro, pac = ctx
    _bloqueo(conn, prof, 0, 120)
    with pytest.raises(IntegrityError) as exc:
        _turno(conn, prof, pac, 30, 60)
    assert _sqlstate(exc.value) == "23P01"


def test_insert_turno_confirmado_dentro_de_bloqueo_rechazado(ctx):
    conn, prof, _otro, pac = ctx
    _bloqueo(conn, prof, 0, 120)
    with pytest.raises(IntegrityError) as exc:
        _turno(conn, prof, pac, 90, 150, estado="confirmado")  # cruza el borde final
    assert _sqlstate(exc.value) == "23P01"


def test_turno_contiguo_al_bloqueo_aceptado(ctx):
    conn, prof, _otro, pac = ctx
    _bloqueo(conn, prof, 60, 120)
    _turno(conn, prof, pac, 30, 60)  # termina justo donde empieza el bloqueo
    _turno(conn, prof, pac, 120, 150)  # empieza justo donde termina


def test_bloqueo_inactivo_no_frena_turno(ctx):
    conn, prof, _otro, pac = ctx
    _bloqueo(conn, prof, 0, 120, activo=False)
    _turno(conn, prof, pac, 30, 60)


def test_bloqueo_de_otro_profesional_no_frena_turno(ctx):
    conn, prof, otro, pac = ctx
    _bloqueo(conn, otro, 0, 120)
    _turno(conn, prof, pac, 30, 60)


def test_turno_cancelado_dentro_de_bloqueo_aceptado(ctx):
    conn, prof, _otro, pac = ctx
    _bloqueo(conn, prof, 0, 120)
    _turno(conn, prof, pac, 30, 60, estado="cancelado")


def test_sobreturno_dentro_de_bloqueo_rechazado(ctx):
    """El sobreturno exime del solape entre turnos, nunca de un bloqueo."""
    conn, prof, _otro, pac = ctx
    _bloqueo(conn, prof, 0, 120)
    with pytest.raises(IntegrityError) as exc:
        _turno(conn, prof, pac, 30, 60, sobreturno=True)
    assert _sqlstate(exc.value) == "23P01"


def test_update_que_mueve_turno_dentro_de_bloqueo_rechazado(ctx):
    conn, prof, _otro, pac = ctx
    _bloqueo(conn, prof, 200, 260)
    tid = _turno(conn, prof, pac, 0, 30)
    with pytest.raises(IntegrityError) as exc:
        conn.execute(
            sa.text("UPDATE turnos SET inicio = :i, fin = :f WHERE id = :id"),
            {"i": _h(210), "f": _h(240), "id": tid},
        )
    assert _sqlstate(exc.value) == "23P01"


def _sin_triggers(conn: sa.Connection) -> None:
    for tabla in ("turnos", "bloqueos"):
        conn.execute(sa.text(f"ALTER TABLE {tabla} DISABLE TRIGGER USER"))


def _con_triggers(conn: sa.Connection) -> None:
    for tabla in ("turnos", "bloqueos"):
        conn.execute(sa.text(f"ALTER TABLE {tabla} ENABLE TRIGGER USER"))


def test_update_solo_de_estado_no_dispara_el_trigger(ctx):
    """Un turno preexistente dentro de un bloqueo (insertado con los triggers deshabilitados)
    puede pasar a `cancelado`/`atendido`: el trigger es `UPDATE OF inicio, fin, profesional_id`."""
    conn, prof, _otro, pac = ctx
    _sin_triggers(conn)
    a = _turno(conn, prof, pac, 30, 60)
    b = _turno(conn, prof, pac, 90, 100, sobreturno=True)
    _bloqueo(conn, prof, 0, 120)
    _con_triggers(conn)
    conn.execute(sa.text("UPDATE turnos SET estado = 'cancelado' WHERE id = :id"), {"id": a})
    conn.execute(sa.text("UPDATE turnos SET estado = 'atendido' WHERE id = :id"), {"id": b})
    estados = {
        r[0]
        for r in conn.execute(
            sa.text("SELECT estado::text FROM turnos WHERE id IN (:a, :b)"), {"a": a, "b": b}
        )
    }
    assert estados == {"cancelado", "atendido"}


# --- 2.3 trigger bloqueos -> turnos ------------------------------------------------------


def test_insert_bloqueo_sobre_turno_confirmado_rechazado(ctx):
    conn, prof, _otro, pac = ctx
    _turno(conn, prof, pac, 30, 60, estado="confirmado")
    with pytest.raises(IntegrityError) as exc:
        _bloqueo(conn, prof, 0, 120)
    assert _sqlstate(exc.value) == "23P01"


def test_insert_bloqueo_sobre_turno_reservado_rechazado(ctx):
    conn, prof, _otro, pac = ctx
    _turno(conn, prof, pac, 30, 60)
    with pytest.raises(IntegrityError) as exc:
        _bloqueo(conn, prof, 50, 90)  # cruza solo el final del turno
    assert _sqlstate(exc.value) == "23P01"


def test_bloqueo_sobre_turno_cancelado_o_de_otro_profesional_aceptado(ctx):
    conn, prof, otro, pac = ctx
    _turno(conn, prof, pac, 30, 60, estado="cancelado")
    _turno(conn, otro, pac, 30, 60)
    _bloqueo(conn, prof, 0, 120)


def test_bloqueo_contiguo_al_turno_aceptado(ctx):
    conn, prof, _otro, pac = ctx
    _turno(conn, prof, pac, 30, 60)
    _bloqueo(conn, prof, 60, 120)
    _bloqueo(conn, prof, 0, 30)


def test_bloqueo_inactivo_sobre_turno_aceptado(ctx):
    conn, prof, _otro, pac = ctx
    _turno(conn, prof, pac, 30, 60)
    _bloqueo(conn, prof, 0, 120, activo=False)


def test_reactivar_bloqueo_sobre_turno_reservado_rechazado(ctx):
    conn, prof, _otro, pac = ctx
    bid = _bloqueo(conn, prof, 0, 120, activo=False)
    _turno(conn, prof, pac, 30, 60)
    with pytest.raises(IntegrityError) as exc:
        conn.execute(sa.text("UPDATE bloqueos SET is_active = true WHERE id = :id"), {"id": bid})
    assert _sqlstate(exc.value) == "23P01"


def test_ampliar_bloqueo_activo_sobre_turno_rechazado(ctx):
    conn, prof, _otro, pac = ctx
    bid = _bloqueo(conn, prof, 0, 30)
    _turno(conn, prof, pac, 60, 90)
    with pytest.raises(IntegrityError) as exc:
        conn.execute(
            sa.text("UPDATE bloqueos SET hasta = :h WHERE id = :id"), {"h": _h(120), "id": bid}
        )
    assert _sqlstate(exc.value) == "23P01"


def test_dar_de_baja_bloqueo_nunca_falla(ctx):
    conn, prof, _otro, pac = ctx
    _sin_triggers(conn)
    bid = _bloqueo(conn, prof, 0, 120)
    _turno(conn, prof, pac, 30, 60)  # inconsistente a proposito (triggers apagados)
    _con_triggers(conn)
    conn.execute(sa.text("UPDATE bloqueos SET is_active = false WHERE id = :id"), {"id": bid})
    assert conn.execute(
        sa.text("SELECT is_active FROM bloqueos WHERE id = :id"), {"id": bid}
    ).scalar_one() is False


def test_bloqueos_superpuestos_entre_si_aceptados(ctx):
    conn, prof, _otro, _pac = ctx
    _bloqueo(conn, prof, 0, 120)
    _bloqueo(conn, prof, 60, 180)


# --- 2.4 verificación previa y reversibilidad -------------------------------------------

TRIGGERS_003 = {"tg_turnos_sin_bloqueo_ins", "tg_turnos_sin_bloqueo_upd", "tg_bloqueos_sin_turnos"}


def _nombres(engine: sa.Engine, query: str) -> set[str]:
    with engine.connect() as c:
        return {r[0] for r in c.execute(sa.text(query))}


def _sembrar_en_002(url: str, *, inconsistente: bool) -> None:
    """Un profesional con un turno activo y un bloqueo activo (solapado o no) en la DB a 002."""
    engine = sa.create_engine(url)
    try:
        with engine.begin() as c:
            prof = uuid.uuid4()
            c.execute(
                sa.text(
                    "INSERT INTO profesionales (id, nombre, matricula) VALUES (:id, 'Dr. S', :m)"
                ),
                {"id": prof, "m": f"MAT-{prof.hex[:8]}"},
            )
            pac = _paciente(c)
            _turno(c, prof, pac, 30, 60)
            _bloqueo(c, prof, 0, 120) if inconsistente else _bloqueo(c, prof, 60, 120)
    finally:
        engine.dispose()


def test_upgrade_aborta_con_datos_inconsistentes():
    with db_temporal() as url:
        assert alembic(url, "upgrade", "002").returncode == 0
        _sembrar_en_002(url, inconsistente=True)
        res = alembic(url, "upgrade", "003")
        assert res.returncode != 0
        assert "003" in res.stderr or "bloqueo" in res.stderr.lower()
        engine = sa.create_engine(url)
        try:
            assert not (TRIGGERS_003 & _nombres(engine, "SELECT tgname FROM pg_trigger"))
            columnas = _nombres(
                engine,
                "SELECT column_name FROM information_schema.columns WHERE table_name='profesionales'",
            )
            assert "user_id" not in columnas  # el upgrade es transaccional: nada quedó a medias
            assert alembic(url, "current").stdout.strip().startswith("002")
        finally:
            engine.dispose()


def test_upgrade_con_datos_consistentes_conserva_filas_y_crea_triggers():
    with db_temporal() as url:
        assert alembic(url, "upgrade", "002").returncode == 0
        _sembrar_en_002(url, inconsistente=False)
        assert alembic(url, "upgrade", "003").returncode == 0
        engine = sa.create_engine(url)
        try:
            assert TRIGGERS_003 <= _nombres(engine, "SELECT tgname FROM pg_trigger")
            with engine.connect() as c:
                assert c.execute(sa.text("SELECT count(*) FROM turnos")).scalar_one() == 1
                assert c.execute(sa.text("SELECT count(*) FROM bloqueos")).scalar_one() == 1
        finally:
            engine.dispose()


def test_ciclo_up_down_up_deja_esquema_identico_y_conserva_filas():
    with db_temporal() as url:
        assert alembic(url, "upgrade", "002").returncode == 0
        _sembrar_en_002(url, inconsistente=False)
        assert alembic(url, "upgrade", "003").returncode == 0
        engine = sa.create_engine(url)
        try:
            primero = snapshot_esquema(engine)
            assert any(r[1] == "tg_bloqueos_sin_turnos" for r in primero["triggers"])
            assert any(r[:2] == ("profesionales", "user_id") for r in primero["columnas"])
            assert alembic(url, "downgrade", "002").returncode == 0
            assert not (TRIGGERS_003 & _nombres(engine, "SELECT tgname FROM pg_trigger"))
            assert "turno_sin_bloqueo" not in _nombres(engine, "SELECT proname FROM pg_proc")
            assert "bloqueo_sin_turnos" not in _nombres(engine, "SELECT proname FROM pg_proc")
            with engine.connect() as c:  # el downgrade conserva los datos de 002
                assert c.execute(sa.text("SELECT count(*) FROM turnos")).scalar_one() == 1
                assert c.execute(sa.text("SELECT count(*) FROM bloqueos")).scalar_one() == 1
            assert alembic(url, "upgrade", "003").returncode == 0
            assert snapshot_esquema(engine) == primero
        finally:
            engine.dispose()


def test_alembic_heads_es_003():
    res = alembic("postgresql+psycopg://x:x@localhost/x", "heads")
    assert res.returncode == 0
    assert res.stdout.strip().startswith("003")


# --- 2.5 misma clave de lock que C-05 (`bloquear_agenda`) --------------------------------


def _bajo_lock_timeout(engine: sa.Engine) -> sa.Connection:
    c = engine.connect()
    c.execute(sa.text("SET lock_timeout = '400ms'"))
    c.commit()
    return c


@pytest.mark.parametrize("que", ["turno", "bloqueo"])
def test_bloquear_agenda_y_trigger_comparten_lock(mig_engine, que):
    from sqlalchemy.orm import Session

    from app.infrastructure.repositories_agenda import TurnoRepository

    with mig_engine.begin() as setup:
        prof, otro, pac = _profesional(setup), _profesional(setup), _paciente(setup)

    def escribir(c: sa.Connection, quien: uuid.UUID) -> None:
        if que == "turno":
            _turno(c, quien, pac, 300, 330)
        else:
            _bloqueo(c, quien, 300, 330)

    retenedor = Session(mig_engine)
    try:
        TurnoRepository(retenedor).bloquear_agenda(prof)  # tx A abierta, sin commit
        conn_b = _bajo_lock_timeout(mig_engine)
        try:
            with pytest.raises(sa.exc.OperationalError) as exc:
                escribir(conn_b, prof)  # mismo profesional: el trigger espera el lock de A
            assert getattr(exc.value.orig, "sqlstate", None) == "55P03"
            conn_b.rollback()
            escribir(conn_b, otro)  # otro profesional: no espera
            conn_b.commit()
        finally:
            conn_b.close()
    finally:
        retenedor.rollback()
        retenedor.close()
