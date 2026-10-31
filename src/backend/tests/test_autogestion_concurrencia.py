"""C-07 7.x: concurrencia real de la autogestion por token (PG real, threads + Barrier)."""

import threading
from collections.abc import Callable
from unittest.mock import patch

import fakeredis
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import AuditoriaTurno, Profesional, Turno, User
from app.main import app
from tests.support_gestion import (
    AHORA,
    auditorias,
    crear_profesional,
    crear_secretaria,
    crear_turno,
    cuenta,
)

ITERACIONES = 5
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


# Los valores ORM se leen ACA (hilo principal): dentro de un hilo, un objeto expirado dispararia
# un refresh sobre la Session compartida del test desde dos hilos a la vez (flaky).


def _por_token(metodo: str, token: str, **kw):
    def tarea(client: TestClient):
        sufijo = "/confirmar" if metodo == "post" else ""
        resp = getattr(client, metodo)(f"/api/turnos/por-token/{token}{sufijo}", **kw)
        return resp.status_code, resp.json()

    return tarea


def _alta_manual(prof_id: str, headers: dict, dia: str, hhmm: str, tel: str):
    def tarea(client: TestClient):
        resp = client.post(
            "/api/turnos/manual",
            json={
                "profesional_id": prof_id,
                "inicio": f"{dia}T{hhmm}:00-03:00",
                "paciente_nombre": "Paciente Manual",
                "paciente_telefono": tel,
            },
            headers=headers,
        )
        return resp.status_code, resp.json()

    return tarea


def _reserva_publica(prof_id: str, dia: str, hhmm: str, tel: str):
    def tarea(client: TestClient):
        resp = client.post(
            "/api/turnos",
            json={
                "profesional_id": prof_id,
                "inicio": f"{dia}T{hhmm}:00-03:00",
                "paciente_nombre": "Paciente Publico",
                "paciente_telefono": tel,
            },
        )
        return resp.status_code, resp.json()

    return tarea


def _solapados(session: Session) -> int:
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


# --- 7.1 confirmar <-> cancelar -----------------------------------------------------------


def test_confirmar_y_cancelar_simultaneos_terminan_cancelado_sin_500(api_client, mig_session, prof):
    exitos_confirmar = 0
    for it in range(ITERACIONES):
        turno = crear_turno(mig_session, prof, "10:00", dia=DIAS[it], telefono=f"+54911000040{it:02d}")
        turno_id, token = turno.id, turno.token_publico

        (s_conf, c_conf), (s_canc, _) = en_paralelo(
            [_por_token("post", token), _por_token("delete", token)]
        )

        assert s_canc == 200  # cancelar siempre termina: no depende del orden
        assert s_conf in (200, 422), (s_conf, c_conf)  # 422 si la cancelacion gano la carrera
        if s_conf == 422:
            assert c_conf["code"] == "transicion_no_permitida"
        mig_session.expire_all()
        assert mig_session.get(Turno, turno_id).estado is EstadoTurno.CANCELADO
        assert len(auditorias(mig_session, turno_id, "cancelar")) == 1
        assert len(auditorias(mig_session, turno_id, "confirmar")) == (1 if s_conf == 200 else 0)
        exitos_confirmar += s_conf == 200

    # auditorias nuevas == operaciones exitosas (cancelar siempre + confirmar cuando gano)
    assert cuenta(mig_session, AuditoriaTurno) == ITERACIONES + exitos_confirmar


# --- 7.2 reprogramar por token vs alta manual / reserva publica ---------------------------


@pytest.mark.parametrize("rival", ["manual", "publica"])
def test_reprogramar_por_token_vs_alta_al_mismo_hueco_un_exito_un_409(
    api_client, mig_session, prof, sec, rival
):
    prof_id = str(prof.id)
    headers = {
        "Authorization": "Bearer "
        + create_access_token(str(sec.id), sec.email, sec.rol.value)
    }
    for it in range(ITERACIONES):
        turno = crear_turno(mig_session, prof, "09:00", dia=DIAS[it], telefono="+5491100005001")
        token, dia = turno.token_publico, DIAS[it]
        patch_tarea = _por_token("patch", token, json={"inicio": f"{dia}T14:00:00-03:00"})
        tel = f"+54911000060{it:02d}"
        rival_tarea = (
            _alta_manual(prof_id, headers, dia, "14:00", tel)
            if rival == "manual"
            else _reserva_publica(prof_id, dia, "14:00", tel)
        )

        resultados = en_paralelo([patch_tarea, rival_tarea])

        estados = sorted(s for s, _ in resultados)
        assert estados in ([200, 409], [201, 409]), (it, resultados)
        for status, cuerpo in resultados:
            if status == 409:
                assert cuerpo["code"] == "hueco_ocupado"
        assert _solapados(mig_session) == 0
