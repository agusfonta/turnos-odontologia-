"""C-06 5.x: POST/DELETE /api/bloqueos (PG real, TestClient)."""

import logging
import uuid
from datetime import timedelta
from unittest.mock import patch

import fakeredis
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import Bloqueo, Profesional, User, UserRole
from app.main import app
from tests.support_gestion import (
    AHORA,
    LUNES,
    crear_profesional,
    crear_secretaria,
    crear_turno,
    cuenta,
    inicio,
)


@pytest.fixture(autouse=True)
def entorno_fijo():
    app.dependency_overrides[get_ahora] = lambda: AHORA
    with patch("app.core.security.get_redis_client", return_value=fakeredis.FakeRedis()):
        yield


@pytest.fixture
def prof(api_client, mig_session: Session) -> Profesional:
    return crear_profesional(mig_session)


@pytest.fixture
def sec(api_client, mig_session: Session) -> User:
    return crear_secretaria(mig_session)


def _auth(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id), user.email, user.rol.value)
    return {"Authorization": f"Bearer {token}"}


def _odontologo(session: Session) -> User:
    user = User(
        email=f"odo-{uuid.uuid4().hex[:6]}@example.test", password_hash="x", rol=UserRole.ODONTOLOGO
    )
    session.add(user)
    session.commit()
    return user


def _body(prof, desde: str = "09:00", hasta: str = "13:00", **extra) -> dict:
    return {
        "profesional_id": str(prof.id),
        "desde": f"{LUNES}T{desde}:00-03:00",
        "hasta": f"{LUNES}T{hasta}:00-03:00",
        "motivo": "Capacitacion",
        **extra,
    }


def _post(api_client, user, body):
    return api_client.post("/api/bloqueos", json=body, headers=_auth(user) if user else {})


def _horas(resp) -> list[str]:
    return [h["inicio"][11:16] for h in resp.json()]


def _disponibilidad(api_client, prof):
    return api_client.get(
        "/api/disponibilidad",
        params={"profesional_id": str(prof.id), "desde": LUNES, "hasta": LUNES},
    )


# --- 5.1 POST /api/bloqueos ----------------------------------------------------------------


def test_crear_201(api_client, mig_session, prof, sec):
    resp = _post(api_client, sec, _body(prof))

    assert resp.status_code == 201, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == {"id", "profesional_id", "desde", "hasta", "motivo"}
    assert cuerpo["profesional_id"] == str(prof.id) and cuerpo["motivo"] == "Capacitacion"
    assert cuerpo["desde"].endswith("-03:00") and cuerpo["hasta"].endswith("-03:00")
    mig_session.expire_all()
    fila = mig_session.get(Bloqueo, uuid.UUID(cuerpo["id"]))
    assert fila.is_active and fila.desde == inicio("09:00")


def test_la_disponibilidad_del_dia_excluye_el_rango_bloqueado(api_client, mig_session, prof, sec):
    assert _horas(_disponibilidad(api_client, prof))[0] == "09:00"

    assert _post(api_client, sec, _body(prof)).status_code == 201

    horas = _horas(_disponibilidad(api_client, prof))
    assert horas[0] == "13:00" and "12:30" not in horas


def test_sin_token_401_y_token_invalido_401(api_client, mig_session, prof):
    assert _post(api_client, None, _body(prof)).status_code == 401
    resp = api_client.post(
        "/api/bloqueos", json=_body(prof), headers={"Authorization": "Bearer basura"}
    )
    assert resp.status_code == 401
    assert cuenta(mig_session, Bloqueo) == 0


def test_odontologo_403_sin_filas(api_client, mig_session, prof):
    odo = _odontologo(mig_session)

    resp = _post(api_client, odo, _body(prof))

    assert resp.status_code == 403
    assert cuenta(mig_session, Bloqueo) == 0


@pytest.mark.parametrize(
    "cambios",
    [
        {"hasta": f"{LUNES}T09:00:00-03:00"},  # hasta == desde
        {"hasta": f"{LUNES}T08:00:00-03:00"},  # hasta < desde
        {"desde": f"{LUNES}T09:00:00"},  # sin zona
        {"motivo": ""},
        {"motivo": "   "},
        {"motivo": "x" * 201},
        {"estado": "x"},  # campo no definido
        {"desde": "2030-02-01T09:00:00-03:00", "hasta": "2030-02-01T10:00:00-03:00"},  # pasado
    ],
)
def test_validaciones_422(api_client, mig_session, prof, sec, cambios):
    resp = _post(api_client, sec, _body(prof, **cambios))

    assert resp.status_code == 422, resp.text
    assert cuenta(mig_session, Bloqueo) == 0


def test_profesional_inexistente_o_inactivo_404(api_client, mig_session, prof, sec):
    otro = type("P", (), {"id": uuid.uuid4()})()
    resp = _post(api_client, sec, _body(otro))
    assert resp.status_code == 404 and resp.json()["code"] == "profesional_no_encontrado"

    prof.is_active = False
    mig_session.commit()
    assert _post(api_client, sec, _body(prof)).status_code == 404
    assert cuenta(mig_session, Bloqueo) == 0


def test_409_bloqueo_con_turnos_lista_sin_datos_de_paciente(api_client, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    resp = _post(api_client, sec, _body(prof))

    assert resp.status_code == 409
    cuerpo = resp.json()
    assert cuerpo["code"] == "bloqueo_con_turnos"
    assert cuerpo["turnos"] == [
        {
            "id": str(turno.id),
            "inicio": f"{LUNES}T10:00:00-03:00",
            "fin": f"{LUNES}T10:30:00-03:00",
            "estado": "reservado",
        }
    ]
    assert "token_publico" not in resp.text and "paciente" not in resp.text
    assert cuenta(mig_session, Bloqueo) == 0


def test_turno_cancelado_o_contiguo_no_impide_el_bloqueo(api_client, mig_session, prof, sec):
    crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CANCELADO, telefono="+5491100000091")
    crear_turno(mig_session, prof, "13:00", telefono="+5491100000092")

    assert _post(api_client, sec, _body(prof)).status_code == 201


def test_bloqueos_superpuestos_201_y_disponibilidad_con_la_union(api_client, mig_session, prof, sec):
    assert _post(api_client, sec, _body(prof, "09:00", "13:00")).status_code == 201
    assert _post(api_client, sec, _body(prof, "12:00", "17:00")).status_code == 201

    assert _horas(_disponibilidad(api_client, prof)) == ["17:00", "17:30"]


def test_alta_registra_log_estructurado_post_retorno(api_client, mig_session, prof, sec, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.bloqueos"):
        resp = _post(api_client, sec, _body(prof))

    bloqueo_id = resp.json()["id"]
    registros = [r for r in caplog.records if r.name == "app.api.bloqueos"]
    assert len(registros) == 1
    r = registros[0]
    assert (r.accion, str(r.bloqueo_id), str(r.profesional_id), str(r.user_id)) == (
        "bloqueo_creado", bloqueo_id, str(prof.id), str(sec.id),
    )


def test_error_no_registra_log_de_alta(api_client, mig_session, prof, sec, caplog):
    crear_turno(mig_session, prof, "10:00")
    with caplog.at_level(logging.INFO, logger="app.api.bloqueos"):
        assert _post(api_client, sec, _body(prof)).status_code == 409

    assert [r for r in caplog.records if r.name == "app.api.bloqueos"] == []


# --- 5.2 DELETE /api/bloqueos/{id} ---------------------------------------------------------


def _crear_directo(api_client, sec, prof, desde="09:00", hasta="13:00") -> str:
    resp = _post(api_client, sec, _body(prof, desde, hasta))
    assert resp.status_code == 201
    return resp.json()["id"]


def test_baja_200(api_client, mig_session, prof, sec):
    bid = _crear_directo(api_client, sec, prof)

    resp = api_client.delete(f"/api/bloqueos/{bid}", headers=_auth(sec))

    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"id", "profesional_id", "desde", "hasta", "motivo"}
    mig_session.expire_all()
    fila = mig_session.get(Bloqueo, uuid.UUID(bid))
    assert fila.is_active is False and fila.deleted_at == AHORA  # la fila se conserva


def test_baja_devuelve_el_hueco_a_la_disponibilidad(api_client, mig_session, prof, sec):
    bid = _crear_directo(api_client, sec, prof)
    assert _horas(_disponibilidad(api_client, prof))[0] == "13:00"

    api_client.delete(f"/api/bloqueos/{bid}", headers=_auth(sec))

    assert _horas(_disponibilidad(api_client, prof))[0] == "09:00"


def test_baja_404_inexistente_y_ya_inactivo(api_client, mig_session, prof, sec):
    resp = api_client.delete(f"/api/bloqueos/{uuid.uuid4()}", headers=_auth(sec))
    assert resp.status_code == 404 and resp.json()["code"] == "bloqueo_no_encontrado"

    bid = _crear_directo(api_client, sec, prof)
    assert api_client.delete(f"/api/bloqueos/{bid}", headers=_auth(sec)).status_code == 200
    again = api_client.delete(f"/api/bloqueos/{bid}", headers=_auth(sec))
    assert again.status_code == 404 and again.json()["code"] == "bloqueo_no_encontrado"


def test_baja_401_403_y_uuid_invalido_422(api_client, mig_session, prof, sec):
    bid = _crear_directo(api_client, sec, prof)
    odo = _odontologo(mig_session)

    assert api_client.delete(f"/api/bloqueos/{bid}").status_code == 401
    assert api_client.delete(f"/api/bloqueos/{bid}", headers=_auth(odo)).status_code == 403
    assert api_client.delete("/api/bloqueos/no-es-uuid", headers=_auth(sec)).status_code == 422
    mig_session.expire_all()
    assert mig_session.get(Bloqueo, uuid.UUID(bid)).is_active is True  # sin cambios


def test_baja_registra_log_estructurado(api_client, mig_session, prof, sec, caplog):
    bid = _crear_directo(api_client, sec, prof)
    with caplog.at_level(logging.INFO, logger="app.api.bloqueos"):
        api_client.delete(f"/api/bloqueos/{bid}", headers=_auth(sec))

    (r,) = [r for r in caplog.records if r.name == "app.api.bloqueos"]
    assert (r.accion, str(r.bloqueo_id), str(r.user_id)) == ("bloqueo_baja", bid, str(sec.id))
