"""C-06 2.6: caracterización de las vías existentes frente al trigger de la 003.

El código de `reservar_turno` / `gestion_turnos` NO cambia: con el chequeo de aplicación
ciego (`hay_ocupacion` -> False), el árbitro es el trigger turno<->bloqueo (23P01) y
las tres vías responden 409 (nunca 500) y no dejan efectos.
"""

from unittest.mock import patch

import fakeredis
import pytest
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.infrastructure.models import AuditoriaTurno, Bloqueo, Paciente, Turno
from app.main import app
from tests.support_gestion import (
    AHORA,
    LUNES,
    cuenta,
    crear_profesional,
    crear_secretaria,
    crear_turno,
    inicio,
)


@pytest.fixture(autouse=True)
def entorno(api_client):
    app.dependency_overrides[get_ahora] = lambda: AHORA
    with patch("app.core.security.get_redis_client", return_value=fakeredis.FakeRedis()):
        yield


@pytest.fixture
def prof(api_client, mig_session: Session):
    return crear_profesional(mig_session)


@pytest.fixture
def sec(api_client, mig_session: Session):
    return crear_secretaria(mig_session)


@pytest.fixture
def ciego(monkeypatch):
    """El chequeo de aplicación nunca ve ocupación: decide la base."""
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)


def _auth(user) -> dict[str, str]:
    token = create_access_token(str(user.id), user.email, user.rol.value)
    return {"Authorization": f"Bearer {token}"}


def _bloquear(session: Session, prof, desde: str = "09:00", hasta: str = "12:00") -> None:
    session.add(
        Bloqueo(profesional_id=prof.id, desde=inicio(desde), hasta=inicio(hasta), motivo="Sintetico")
    )
    session.commit()


def _body(prof, hhmm: str = "10:00", telefono: str = "+5491100000001", **extra) -> dict:
    return {
        "profesional_id": str(prof.id),
        "inicio": f"{LUNES}T{hhmm}:00-03:00",
        "paciente_nombre": "Paciente Sintetico",
        "paciente_telefono": telefono,
        **extra,
    }


def test_reserva_publica_dentro_de_bloqueo_409_via_trigger(
    api_client, mig_session, prof, ciego
):
    _bloquear(mig_session, prof)

    resp = api_client.post("/api/turnos", json=_body(prof))

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert "huecos" in resp.json()
    assert cuenta(mig_session, Turno) == 0
    assert cuenta(mig_session, Paciente) == 0  # rollback del paciente
    assert cuenta(mig_session, AuditoriaTurno) == 0


def test_reserva_publica_fuera_del_bloqueo_sigue_201(api_client, mig_session, prof, ciego):
    _bloquear(mig_session, prof)  # 09:00-12:00

    resp = api_client.post("/api/turnos", json=_body(prof, "12:00"))  # contiguo

    assert resp.status_code == 201, resp.text


def test_alta_manual_dentro_de_bloqueo_409_via_trigger(
    api_client, mig_session, prof, sec, ciego
):
    _bloquear(mig_session, prof)

    resp = api_client.post("/api/turnos/manual", json=_body(prof), headers=_auth(sec))

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert cuenta(mig_session, Turno) == 0 and cuenta(mig_session, Paciente) == 0


def test_alta_manual_sobreturno_dentro_de_bloqueo_409(
    api_client, mig_session, prof, sec, ciego
):
    """El sobreturno exime del solape entre turnos, nunca de un bloqueo (chequeo de bloqueos propio)."""
    _bloquear(mig_session, prof)

    resp = api_client.post(
        "/api/turnos/manual", json=_body(prof, sobreturno=True), headers=_auth(sec)
    )

    assert resp.status_code == 409
    assert cuenta(mig_session, Turno) == 0


def test_reprogramar_hacia_un_bloqueo_409_via_trigger_y_turno_intacto(
    api_client, mig_session, prof, sec, ciego
):
    turno = crear_turno(mig_session, prof, "14:00")
    _bloquear(mig_session, prof)

    resp = api_client.patch(
        f"/api/turnos/{turno.id}",
        json={"inicio": f"{LUNES}T10:00:00-03:00"},
        headers=_auth(sec),
    )

    assert resp.status_code == 409, resp.text
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("14:00")  # sin cambios


def test_reprogramar_a_horario_libre_con_bloqueo_en_otro_tramo_sigue_200(
    api_client, mig_session, prof, sec, ciego
):
    turno = crear_turno(mig_session, prof, "14:00")
    _bloquear(mig_session, prof)  # 09:00-12:00

    resp = api_client.patch(
        f"/api/turnos/{turno.id}",
        json={"inicio": f"{LUNES}T15:00:00-03:00"},
        headers=_auth(sec),
    )

    assert resp.status_code == 200, resp.text


def test_cancelar_turno_preexistente_dentro_de_bloqueo_no_dispara_el_trigger(
    api_client, mig_session, prof, sec
):
    """Cancelar es `UPDATE` solo de estado: aunque el turno viva dentro de un bloqueo
    (inconsistente, creado con triggers apagados), cancelarlo siempre funciona."""
    import sqlalchemy as sa

    turno = crear_turno(mig_session, prof, "10:00")
    mig_session.execute(sa.text("ALTER TABLE bloqueos DISABLE TRIGGER USER"))
    _bloquear(mig_session, prof)
    mig_session.execute(sa.text("ALTER TABLE bloqueos ENABLE TRIGGER USER"))
    mig_session.commit()

    resp = api_client.delete(f"/api/turnos/{turno.id}", headers=_auth(sec))

    assert resp.status_code == 200 and resp.json()["estado"] == "cancelado"
