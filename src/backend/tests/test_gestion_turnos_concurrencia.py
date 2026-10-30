"""C-05 7.x: concurrencia real de gestion de secretaria (PG real, threads + Barrier)."""

import threading
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch

import fakeredis

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.infrastructure.models import AuditoriaTurno, Paciente, Profesional, Turno, User
from app.main import app
from tests.support_gestion import (
    AHORA,
    LUNES,
    auditorias,
    crear_profesional,
    crear_secretaria,
    crear_turno,
    cuenta,
    inicio,
)

ITERACIONES = 5
SLOTS = ["14:00", "14:30", "15:00", "15:30", "16:00"]
DIAS = ["2030-03-11", "2030-03-18", "2030-03-25", "2030-04-01", "2030-04-08"]  # lunes


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
    """Corre cada tarea en un hilo con su propio TestClient, liberadas juntas por una Barrier."""
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


def _alta_manual(prof, sec, hhmm: str, i: int, **extra):
    # Atributos ORM leidos ACA (hilo principal): dentro del hilo, un objeto expirado dispararia un
    # refresh sobre la Session compartida del test desde dos hilos a la vez (flaky).
    prof_id, headers = str(prof.id), _headers(sec)

    def tarea(client: TestClient):
        resp = client.post(
            "/api/turnos/manual",
            json={
                "profesional_id": prof_id,
                "inicio": f"{LUNES}T{hhmm}:00-03:00",
                "paciente_nombre": f"Paciente Sintetico {i}",
                "paciente_telefono": f"+5491100{i:04d}",  # unico por hilo e iteracion (DD-06 reusa por telefono)
                **extra,
            },
            headers=headers,
        )
        return resp.status_code, resp.json()

    return tarea


def _alta_publica(prof, hhmm: str, i: int):
    prof_id = str(prof.id)  # ver nota en `_alta_manual`

    def tarea(client: TestClient):
        resp = client.post(
            "/api/turnos",
            json={
                "profesional_id": prof_id,
                "inicio": f"{LUNES}T{hhmm}:00-03:00",
                "paciente_nombre": f"Paciente Publico {i}",
                "paciente_telefono": f"+54911000020{i:02d}",
            },
        )
        return resp.status_code, resp.json()

    return tarea


def _reprogramar(turno, sec, hhmm: str):
    turno_id, headers = str(turno.id), _headers(sec)  # ver nota en `_alta_manual`

    def tarea(client: TestClient):
        resp = client.patch(
            f"/api/turnos/{turno_id}",
            json={"inicio": f"{LUNES}T{hhmm}:00-03:00"},
            headers=headers,
        )
        return resp.status_code, resp.json()

    return tarea


def _statuses(resultados) -> list[int]:
    return sorted(s for s, _ in resultados)


def _solapados(session: Session) -> int:
    """Pares de turnos no cancelados, sin marca de sobreturno, que se superponen."""
    session.expire_all()
    return session.scalar(
        sa.text(
            """
            SELECT count(*) FROM turnos a JOIN turnos b
              ON a.profesional_id = b.profesional_id AND a.id < b.id
             WHERE a.estado <> 'cancelado' AND b.estado <> 'cancelado'
               AND NOT a.sobreturno AND NOT b.sobreturno
               AND a.inicio < b.fin AND b.inicio < a.fin
            """
        )
    )


# --- 7.1 alta manual concurrente ---------------------------------------------------------


@pytest.mark.parametrize("hilos", [2, 5])
def test_altas_manuales_simultaneas_un_201_resto_409(api_client, mig_session, prof, sec, hilos):
    for it in range(ITERACIONES):
        resultados = en_paralelo([_alta_manual(prof, sec, SLOTS[it], it * 10 + i) for i in range(hilos)])

        assert _statuses(resultados) == [201] + [409] * (hilos - 1), (SLOTS[it], resultados)
        for status, cuerpo in resultados:
            if status == 409:
                assert cuerpo["code"] == "hueco_ocupado"

    assert cuenta(mig_session, Turno) == ITERACIONES  # un unico turno por horario
    assert cuenta(mig_session, Paciente) == ITERACIONES  # sin pacientes huerfanos de los perdedores
    assert cuenta(mig_session, AuditoriaTurno) == ITERACIONES
    assert _solapados(mig_session) == 0


@pytest.mark.parametrize("hilos", [2, 5])
def test_altas_manuales_con_hay_ocupacion_ciego_decide_la_constraint(
    api_client, mig_session, prof, sec, hilos, monkeypatch
):
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)

    for it in range(ITERACIONES):
        resultados = en_paralelo([_alta_manual(prof, sec, SLOTS[it], it * 10 + i) for i in range(hilos)])
        assert _statuses(resultados) == [201] + [409] * (hilos - 1), (SLOTS[it], resultados)

    assert cuenta(mig_session, Turno) == ITERACIONES
    assert cuenta(mig_session, Paciente) == ITERACIONES
    assert _solapados(mig_session) == 0


# --- 7.2 reprogramacion concurrente ------------------------------------------------------


def test_dos_reprogramaciones_al_mismo_hueco_un_200_un_409(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        a = crear_turno(mig_session, prof, "09:00", telefono="+5491100003001", dia=DIAS[it])
        b = crear_turno(mig_session, prof, "09:30", telefono="+5491100003002", dia=DIAS[it])
        dia = a.inicio.date().isoformat()
        destino = f"{dia}T14:00:00-03:00"

        headers = _headers(sec)  # ver nota en `_alta_manual`

        def tarea(turno):
            turno_id = str(turno.id)

            def correr(client: TestClient):
                r = client.patch(f"/api/turnos/{turno_id}", json={"inicio": destino}, headers=headers)
                return r.status_code, r.json()

            return correr

        resultados = en_paralelo([tarea(a), tarea(b)])

        assert _statuses(resultados) == [200, 409], (it, resultados)
        mig_session.expire_all()
        perdedor = a if resultados[0][0] == 409 else b
        assert mig_session.get(Turno, perdedor.id).inicio == perdedor.inicio  # conserva su horario
        assert auditorias(mig_session, perdedor.id) == []

    assert _solapados(mig_session) == 0


def test_reprogramacion_y_alta_publica_al_mismo_hueco(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        t = crear_turno(mig_session, prof, "09:00", telefono="+5491100003001", dia=DIAS[it])
        dia = t.inicio.date().isoformat()
        prof_id, turno_id, headers = str(prof.id), str(t.id), _headers(sec)  # ver `_alta_manual`

        def publica(client: TestClient, dia=dia, it=it):
            r = client.post(
                "/api/turnos",
                json={
                    "profesional_id": prof_id,
                    "inicio": f"{dia}T14:00:00-03:00",
                    "paciente_nombre": "Paciente Publico",
                    "paciente_telefono": f"+54911000020{it:02d}",
                },
            )
            return r.status_code, r.json()

        def mover(client: TestClient, dia=dia):
            r = client.patch(
                f"/api/turnos/{turno_id}", json={"inicio": f"{dia}T14:00:00-03:00"}, headers=headers
            )
            return r.status_code, r.json()

        resultados = en_paralelo([publica, mover])

        assert 500 not in _statuses(resultados), resultados
        assert sorted(s for s in _statuses(resultados)) in ([200, 409], [201, 409]), (it, resultados)

    assert _solapados(mig_session) == 0


def test_reprogramacion_y_alta_manual_al_mismo_hueco(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        t = crear_turno(mig_session, prof, "09:00", telefono="+5491100003001", dia=DIAS[it])
        dia = t.inicio.date().isoformat()
        prof_id, turno_id, headers = str(prof.id), str(t.id), _headers(sec)  # ver `_alta_manual`

        def manual(client: TestClient, dia=dia, it=it):
            r = client.post(
                "/api/turnos/manual",
                json={
                    "profesional_id": prof_id,
                    "inicio": f"{dia}T14:00:00-03:00",
                    "paciente_nombre": "Paciente Manual",
                    "paciente_telefono": f"+54911000040{it:02d}",
                },
                headers=headers,
            )
            return r.status_code, r.json()

        def mover(client: TestClient, dia=dia):
            r = client.patch(
                f"/api/turnos/{turno_id}", json={"inicio": f"{dia}T14:00:00-03:00"}, headers=headers
            )
            return r.status_code, r.json()

        resultados = en_paralelo([manual, mover])

        assert sorted(_statuses(resultados)) in ([200, 409], [201, 409]), (it, resultados)

    assert _solapados(mig_session) == 0


def test_reprogramaciones_cruzadas_sin_500_ni_solapes(api_client, mig_session, prof, sec):
    for it in range(ITERACIONES):
        dia = DIAS[it]
        a = crear_turno(mig_session, prof, "10:00", telefono="+5491100003001", dia=dia)
        b = crear_turno(mig_session, prof, "10:30", telefono="+5491100003002", dia=dia)

        headers = _headers(sec)  # ver nota en `_alta_manual`

        def cruzar(turno, destino: str):
            turno_id = str(turno.id)

            def correr(client: TestClient):
                r = client.patch(
                    f"/api/turnos/{turno_id}",
                    json={"inicio": f"{dia}T{destino}:00-03:00"},
                    headers=headers,
                )
                return r.status_code, r.json()

            return correr

        resultados = en_paralelo([cruzar(a, "10:30"), cruzar(b, "10:00")])

        statuses = _statuses(resultados)
        assert 500 not in statuses, (it, resultados)
        assert statuses.count(200) <= 1, (it, resultados)
        assert _solapados(mig_session) == 0, (it, resultados)

    assert cuenta(mig_session, Turno) == 2 * ITERACIONES
