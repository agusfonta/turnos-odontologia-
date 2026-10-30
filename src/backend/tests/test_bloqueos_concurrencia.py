"""C-06 7.x: concurrencia real bloqueo <-> turno (PG real, threads + Barrier, un TestClient por hilo).

Invariante: nunca queda un turno `reservado`/`confirmado` dentro de un bloqueo activo (DD-08),
ninguna vía responde 500. Los tests "deterministas" sostienen una transacción abierta con SQL
directo para probar que cada trigger toma el advisory lock del profesional (un test de carrera
pura puede pasar aunque falte el lock: la ventana es de milisegundos).
"""

import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime

import fakeredis
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.infrastructure.models import Bloqueo, Profesional, Turno, User
from app.infrastructure.repositories_agenda import BloqueoRepository
from app.main import app
from tests.support_gestion import (
    AHORA,
    crear_profesional,
    crear_secretaria,
    crear_turno,
    cuenta,
    inicio,
)

ITERACIONES = 5
DIAS = ["2030-03-11", "2030-03-18", "2030-03-25", "2030-04-01", "2030-04-08"]  # lunes (9-18)
SLOTS = ["14:00", "14:30", "15:00", "15:30", "16:00"]


@pytest.fixture(autouse=True)
def entorno(api_client):
    app.dependency_overrides[get_ahora] = lambda: AHORA
    with patch("app.core.security.get_redis_client", return_value=fakeredis.FakeRedis()):
        yield


@pytest.fixture
def prof(api_client, mig_session: Session) -> Profesional:
    return crear_profesional(mig_session)


@pytest.fixture
def sec(api_client, mig_session: Session) -> User:
    return crear_secretaria(mig_session)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id), user.email, user.rol.value)
    return {"Authorization": f"Bearer {token}"}


def en_paralelo(tareas: list[Callable[[TestClient], tuple[int, dict]]]) -> list[tuple[int, dict]]:
    """Cada tarea en un hilo con su propio TestClient, liberadas juntas por una Barrier."""
    barrera = threading.Barrier(len(tareas))
    resultados: list[tuple[int, dict]] = [(0, {})] * len(tareas)
    errores: list[BaseException] = []

    def trabajar(i: int) -> None:
        try:
            client = TestClient(app)
            barrera.wait(timeout=10)
            resultados[i] = tareas[i](client)
        except BaseException as exc:  # noqa: BLE001 - se re-lanza en el hilo principal
            errores.append(exc)

    hilos = [threading.Thread(target=trabajar, args=(i,)) for i in range(len(tareas))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    assert not errores, errores
    assert all(s != 0 for s, _ in resultados), "un hilo no termino"
    return resultados


def _bloquear(prof, sec, dia: str, desde: str = "09:00", hasta: str = "13:00"):
    # Atributos ORM leidos ACA (hilo principal): dentro del hilo, un objeto expirado dispararia un
    # refresh sobre la Session compartida del test desde dos hilos a la vez (flaky).
    prof_id, headers = str(prof.id), _headers(sec)

    def tarea(client: TestClient):
        r = client.post(
            "/api/bloqueos",
            json={
                "profesional_id": prof_id,
                "desde": f"{dia}T{desde}:00-03:00",
                "hasta": f"{dia}T{hasta}:00-03:00",
                "motivo": "Capacitacion sintetica",
            },
            headers=headers,
        )
        return r.status_code, r.json()

    return tarea


def _reserva_publica(prof, dia: str, hhmm: str, i: int):
    prof_id = str(prof.id)  # ver nota en `_bloquear`

    def tarea(client: TestClient):
        r = client.post(
            "/api/turnos",
            json={
                "profesional_id": prof_id,
                "inicio": f"{dia}T{hhmm}:00-03:00",
                "paciente_nombre": f"Paciente Publico {i}",
                "paciente_telefono": f"+54911000050{i:02d}",
            },
        )
        return r.status_code, r.json()

    return tarea


def _alta_manual(prof, sec, dia: str, hhmm: str, i: int):
    prof_id, headers = str(prof.id), _headers(sec)  # ver nota en `_bloquear`

    def tarea(client: TestClient):
        r = client.post(
            "/api/turnos/manual",
            json={
                "profesional_id": prof_id,
                "inicio": f"{dia}T{hhmm}:00-03:00",
                "paciente_nombre": f"Paciente Manual {i}",
                "paciente_telefono": f"+54911000060{i:02d}",
            },
            headers=headers,
        )
        return r.status_code, r.json()

    return tarea


def _reprogramar(turno_id, sec, dia: str, hhmm: str):
    headers = _headers(sec)  # ver nota en `_bloquear`

    def tarea(client: TestClient):
        r = client.patch(
            f"/api/turnos/{turno_id}",
            json={"inicio": f"{dia}T{hhmm}:00-03:00"},
            headers=headers,
        )
        return r.status_code, r.json()

    return tarea


def _statuses(resultados) -> list[int]:
    return sorted(s for s, _ in resultados)


def _pares_superpuestos(session: Session) -> int:
    """Pares turno activo <-> bloqueo activo del mismo profesional que se superponen."""
    session.expire_all()
    return session.scalar(
        sa.text(
            """
            SELECT count(*) FROM turnos t JOIN bloqueos b
              ON t.profesional_id = b.profesional_id
             WHERE b.is_active AND t.estado IN ('reservado', 'confirmado')
               AND t.inicio < b.hasta AND t.fin > b.desde
            """
        )
    )


# --- 7.1 bloqueo vs reserva publica ------------------------------------------------------


def test_bloqueo_y_reserva_publica_un_exito_un_409(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        resultados = en_paralelo(
            [_bloquear(prof, sec, DIAS[it]), _reserva_publica(prof, DIAS[it], "10:00", it)]
        )

        assert _statuses(resultados) == [201, 409], (it, resultados)
        codigo_409 = next(c["code"] for s, c in resultados if s == 409)
        assert codigo_409 in {"bloqueo_con_turnos", "hueco_ocupado"}
        assert _pares_superpuestos(mig_session) == 0


def test_bloqueo_y_reserva_publica_con_chequeos_de_aplicacion_ciegos(
    api_client, mig_session, prof, sec, monkeypatch
):
    """Solo deciden los triggers (mismo resultado)."""
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)
    monkeypatch.setattr(BloqueoRepository, "turnos_activos_en_rango", lambda *a, **k: [])

    for it in range(ITERACIONES):
        resultados = en_paralelo(
            [_bloquear(prof, sec, DIAS[it]), _reserva_publica(prof, DIAS[it], "10:00", it)]
        )

        assert _statuses(resultados) == [201, 409], (it, resultados)
        assert _pares_superpuestos(mig_session) == 0


# --- deterministas: el trigger toma el advisory lock del profesional -----------------------


def _conn_abierta(engine: sa.Engine) -> sa.Connection:
    conn = engine.connect()
    conn.execute(sa.text("SELECT 1"))  # abre la transaccion
    return conn


def _correr_en_hilo(tarea: Callable[[TestClient], tuple[int, dict]]):
    salida: dict[str, object] = {}

    def trabajar() -> None:
        try:
            salida["r"] = tarea(TestClient(app))
        except BaseException as exc:  # noqa: BLE001
            salida["e"] = exc

    hilo = threading.Thread(target=trabajar)
    hilo.start()
    return hilo, salida


def test_trigger_de_turnos_toma_el_lock_y_el_bloqueo_espera_al_commit(
    api_client, mig_engine, mig_session, prof, sec
):
    """Tx A inserta un turno por SQL (el trigger toma el lock y NO commitea): un `POST /bloqueos`
    del mismo profesional debe esperar y, tras el commit, ver el turno y responder 409."""
    dia = DIAS[0]
    conn = _conn_abierta(mig_engine)
    try:
        pac = uuid.uuid4()
        conn.execute(
            sa.text("INSERT INTO pacientes (id, nombre, telefono) VALUES (:i, 'P', '+5491100000070')"),
            {"i": pac},
        )
        conn.execute(
            sa.text(
                "INSERT INTO turnos (id, profesional_id, paciente_id, inicio, fin, estado, origen) "
                "VALUES (:i, :p, :pac, :ini, :fin, 'reservado', 'online')"
            ),
            {"i": uuid.uuid4(), "p": prof.id, "pac": pac, "ini": inicio("10:00", dia), "fin": inicio("10:30", dia)},
        )
        hilo, salida = _correr_en_hilo(_bloquear(prof, sec, dia))
        time.sleep(0.7)
        assert hilo.is_alive(), "el bloqueo no espero: falta el lock del trigger de turnos"
        conn.commit()
    finally:
        conn.close()
    hilo.join(timeout=30)

    assert "e" not in salida, salida
    status, cuerpo = salida["r"]
    assert status == 409 and cuerpo["code"] == "bloqueo_con_turnos"
    assert cuenta(mig_session, Bloqueo) == 0 and _pares_superpuestos(mig_session) == 0


def test_trigger_de_bloqueos_toma_el_lock_y_la_reserva_espera_al_commit(
    api_client, mig_engine, mig_session, prof
):
    """Tx A inserta un bloqueo por SQL (el trigger toma el lock y NO commitea): una reserva
    publica dentro del rango debe esperar y, tras el commit, chocar con el bloqueo (409)."""
    dia = DIAS[1]
    conn = _conn_abierta(mig_engine)
    try:
        conn.execute(
            sa.text(
                "INSERT INTO bloqueos (id, profesional_id, desde, hasta, motivo) "
                "VALUES (:i, :p, :d, :h, 'Sintetico')"
            ),
            {"i": uuid.uuid4(), "p": prof.id, "d": inicio("09:00", dia), "h": inicio("13:00", dia)},
        )
        hilo, salida = _correr_en_hilo(_reserva_publica(prof, dia, "10:00", 0))
        time.sleep(0.7)
        assert hilo.is_alive(), "la reserva no espero: falta el lock del trigger de bloqueos"
        conn.commit()
    finally:
        conn.close()
    hilo.join(timeout=30)

    assert "e" not in salida, salida
    status, cuerpo = salida["r"]
    assert status == 409 and cuerpo["code"] == "hueco_ocupado"
    assert cuenta(mig_session, Turno) == 0 and _pares_superpuestos(mig_session) == 0


# --- 7.2 bloqueo vs alta manual / reprogramacion -------------------------------------------


def test_bloqueo_y_alta_manual_un_exito_un_409(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        resultados = en_paralelo(
            [_bloquear(prof, sec, DIAS[it]), _alta_manual(prof, sec, DIAS[it], "10:00", it)]
        )

        assert _statuses(resultados) == [201, 409], (it, resultados)
        assert _pares_superpuestos(mig_session) == 0


def test_bloqueo_y_reprogramacion_al_mismo_rango_un_exito_un_409(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        turno = crear_turno(mig_session, prof, "09:00", dia=DIAS[it], telefono=f"+54911000070{it:02d}")

        resultados = en_paralelo(
            [
                _bloquear(prof, sec, DIAS[it], "13:00", "17:00"),
                _reprogramar(turno.id, sec, DIAS[it], "14:00"),
            ]
        )

        assert _statuses(resultados) == [200, 409] or _statuses(resultados) == [201, 409], (it, resultados)
        assert 500 not in _statuses(resultados)
        assert _pares_superpuestos(mig_session) == 0


# --- 7.3 reservas simultaneas + un bloqueo que pisa una sola -------------------------------


def test_cinco_reservas_y_un_bloqueo_que_pisa_solo_una(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        dia = DIAS[it]
        tareas = [_reserva_publica(prof, dia, hhmm, it * 10 + i) for i, hhmm in enumerate(SLOTS)]
        tareas.append(_bloquear(prof, sec, dia, "15:00", "15:30"))  # pisa solo el slot de las 15:00

        resultados = en_paralelo(tareas)

        estados = _statuses(resultados)
        assert 500 not in estados, (it, resultados)
        assert estados == [201] * 5 + [409], (it, resultados)  # el bloqueo o la reserva de 15:00 pierde
        assert _pares_superpuestos(mig_session) == 0
