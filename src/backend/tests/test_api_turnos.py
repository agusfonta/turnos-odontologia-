"""C-04 4.1-4.3 y 4.5: POST /api/turnos (reserva publica y de secretaria), PG real."""

import uuid
from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import fakeredis
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.infrastructure.models import (
    AuditoriaTurno,
    Bloqueo,
    HorarioProfesional,
    Paciente,
    Profesional,
    Tratamiento,
    Turno,
    User,
    UserRole,
)
from app.main import app

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
LUNES = "2030-03-04"  # weekday() == 0


@pytest.fixture(autouse=True)
def reloj_fijo():
    app.dependency_overrides[get_ahora] = lambda: AHORA
    yield


def _prof(session: Session, slot: int = 30, franjas=((time(9), time(18)),), **kw) -> Profesional:
    prof = Profesional(
        nombre="Dra. Sintetica", matricula=f"MAT-{uuid.uuid4().hex[:8]}", slot_default_min=slot, **kw
    )
    session.add(prof)
    session.flush()
    for ini, fin in franjas:
        session.add(
            HorarioProfesional(profesional_id=prof.id, dia_semana=0, hora_inicio=ini, hora_fin=fin)
        )
    session.commit()
    return prof


def _body(prof, hhmm: str = "10:00", **extra) -> dict:
    return {
        "profesional_id": str(prof.id),
        "inicio": f"{LUNES}T{hhmm}:00-03:00",
        "paciente_nombre": "Paciente Sintetico",
        "paciente_telefono": "+5491100000000",
        **extra,
    }


def _cuenta(session: Session, modelo) -> int:
    session.expire_all()
    return session.scalar(sa.select(sa.func.count()).select_from(modelo))


def _sin_efectos(session: Session) -> None:
    assert _cuenta(session, Turno) == 0
    assert _cuenta(session, Paciente) == 0
    assert _cuenta(session, AuditoriaTurno) == 0


# --- 4.1 reserva publica feliz ------------------------------------------------


def test_reserva_publica_crea_turno_reservado_con_token(api_client, mig_session: Session):
    prof = _prof(mig_session)

    resp = api_client.post("/api/turnos", json=_body(prof))

    assert resp.status_code == 201, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == {
        "id", "profesional_id", "tratamiento_id", "inicio", "fin", "estado", "origen",
        "token_publico",
    }  # fmt: skip
    assert cuerpo["estado"] == "reservado" and cuerpo["origen"] == "online"
    assert cuerpo["profesional_id"] == str(prof.id) and cuerpo["tratamiento_id"] is None
    assert len(cuerpo["token_publico"]) >= 43  # token_urlsafe(32): 256 bits
    turno = mig_session.get(Turno, uuid.UUID(cuerpo["id"]))
    assert turno.token_publico == cuerpo["token_publico"] and turno.created_by is None


def test_fin_es_inicio_mas_duracion_de_tratamiento_o_slot(api_client, mig_session: Session):
    prof = _prof(mig_session)
    trat = Tratamiento(nombre="Conducto", duracion_min=60)
    mig_session.add(trat)
    mig_session.commit()

    con_trat = api_client.post("/api/turnos", json=_body(prof, "10:00", tratamiento_id=trat.id))
    sin_trat = api_client.post("/api/turnos", json=_body(prof, "14:00"))

    assert con_trat.json()["fin"] == f"{LUNES}T11:00:00-03:00"
    assert con_trat.json()["tratamiento_id"] == trat.id
    assert sin_trat.json()["fin"] == f"{LUNES}T14:30:00-03:00"


def test_paciente_persistido_con_datos_enviados(api_client, mig_session: Session):
    prof = _prof(mig_session)

    resp = api_client.post(
        "/api/turnos",
        json=_body(prof, paciente_nombre="Ana Sintetica", paciente_telefono="+5491155550000"),
    )

    turno = mig_session.get(Turno, uuid.UUID(resp.json()["id"]))
    pac = mig_session.get(Paciente, turno.paciente_id)
    assert (pac.nombre, pac.telefono) == ("Ana Sintetica", "+5491155550000")


def test_exactamente_una_auditoria_crear_actor_paciente(api_client, mig_session: Session):
    prof = _prof(mig_session)

    resp = api_client.post("/api/turnos", json=_body(prof))

    mig_session.expire_all()
    (aud,) = mig_session.scalars(sa.select(AuditoriaTurno)).all()
    assert str(aud.turno_id) == resp.json()["id"]
    assert aud.accion == "crear" and aud.actor_tipo.value == "paciente"
    assert aud.actor_user_id is None


def test_inicio_en_utc_se_acepta_y_vuelve_con_offset_de_clinica(api_client, mig_session: Session):
    prof = _prof(mig_session)
    body = _body(prof)
    body["inicio"] = f"{LUNES}T13:00:00Z"  # 10:00 -03:00

    resp = api_client.post("/api/turnos", json=body)

    assert resp.status_code == 201, resp.text
    assert resp.json()["inicio"] == f"{LUNES}T10:00:00-03:00"
    assert resp.json()["fin"] == f"{LUNES}T10:30:00-03:00"


def test_tokens_distintos_en_dos_reservas(api_client, mig_session: Session):
    prof = _prof(mig_session)

    a = api_client.post("/api/turnos", json=_body(prof, "10:00")).json()
    b = api_client.post("/api/turnos", json=_body(prof, "10:30")).json()

    assert a["token_publico"] != b["token_publico"]


# --- 4.2 validaciones 422 / 404 ---------------------------------------------


def test_telefono_invalido_422_sin_efectos(api_client, mig_session: Session):
    prof = _prof(mig_session)

    resp = api_client.post("/api/turnos", json=_body(prof, paciente_telefono="12345"))

    assert resp.status_code == 422
    assert "paciente_telefono" in str(resp.json()["detail"])
    _sin_efectos(mig_session)


@pytest.mark.parametrize(
    "cambios",
    [
        {"paciente_nombre": ""},
        {"paciente_nombre": "   "},
        {"inicio": f"{LUNES}T10:00:00"},  # naive
        {"fin": f"{LUNES}T10:30:00-03:00"},  # el cliente no define la duracion
        {"sobreturno": True},
        {"campo_fantasma": 1},
    ],
)
def test_cuerpo_invalido_422_sin_efectos(api_client, mig_session: Session, cambios):
    prof = _prof(mig_session)

    resp = api_client.post("/api/turnos", json=_body(prof, **cambios))

    assert resp.status_code == 422
    _sin_efectos(mig_session)


def test_faltante_requerido_422(api_client, mig_session: Session):
    prof = _prof(mig_session)
    body = _body(prof)
    del body["paciente_telefono"]

    assert api_client.post("/api/turnos", json=body).status_code == 422
    _sin_efectos(mig_session)


@pytest.mark.parametrize(
    "hhmm",
    ["10:10", "08:30", "18:00", "17:45"],  # fuera de grilla / antes / fin de franja / fuera de grilla
)
def test_inicio_fuera_de_grilla_o_franja_422_inicio_invalido(api_client, mig_session, hhmm):
    prof = _prof(mig_session)

    resp = api_client.post("/api/turnos", json=_body(prof, hhmm))

    assert resp.status_code == 422
    assert resp.json()["code"] == "inicio_invalido"
    _sin_efectos(mig_session)


def test_inicio_cruzando_dos_franjas_422(api_client, mig_session: Session):
    prof = _prof(mig_session, franjas=((time(9), time(13)), (time(13), time(17))))
    trat = Tratamiento(nombre="Conducto", duracion_min=60)
    mig_session.add(trat)
    mig_session.commit()

    resp = api_client.post("/api/turnos", json=_body(prof, "12:30", tratamiento_id=trat.id))

    assert resp.status_code == 422 and resp.json()["code"] == "inicio_invalido"
    _sin_efectos(mig_session)


def test_profesional_sin_franjas_422(api_client, mig_session: Session):
    prof = _prof(mig_session, franjas=())

    resp = api_client.post("/api/turnos", json=_body(prof))

    assert resp.status_code == 422 and resp.json()["code"] == "inicio_invalido"
    _sin_efectos(mig_session)


def test_inicio_en_el_pasado_422(api_client, mig_session: Session):
    prof = _prof(mig_session)
    app.dependency_overrides[get_ahora] = lambda: datetime(2030, 3, 4, 14, 0, tzinfo=TZ)

    resp = api_client.post("/api/turnos", json=_body(prof, "10:00"))

    assert resp.status_code == 422 and resp.json()["code"] == "inicio_invalido"
    _sin_efectos(mig_session)


def test_profesional_inexistente_o_inactivo_404(api_client, mig_session: Session):
    inactivo = _prof(mig_session, is_active=False)

    assert api_client.post("/api/turnos", json=_body(inactivo)).status_code == 404
    body = _body(inactivo)
    body["profesional_id"] = str(uuid.uuid4())
    assert api_client.post("/api/turnos", json=body).status_code == 404
    _sin_efectos(mig_session)


def test_tratamiento_inactivo_o_inexistente_404(api_client, mig_session: Session):
    prof = _prof(mig_session)
    baja = Tratamiento(nombre="Baja", duracion_min=30, is_active=False)
    mig_session.add(baja)
    mig_session.commit()

    r1 = api_client.post("/api/turnos", json=_body(prof, tratamiento_id=baja.id))
    r2 = api_client.post("/api/turnos", json=_body(prof, tratamiento_id=99999))

    assert r1.status_code == r2.status_code == 404
    assert r1.json()["code"] == "tratamiento_no_encontrado"
    _sin_efectos(mig_session)


# --- 4.3 conflicto 409 ---------------------------------------------------------


def _horas(huecos: list[dict]) -> list[str]:
    return [h["inicio"][11:16] for h in huecos]


def test_hueco_ocupado_409_con_huecos_actualizados(api_client, mig_session: Session):
    prof = _prof(mig_session)
    assert api_client.post("/api/turnos", json=_body(prof, "10:00")).status_code == 201

    resp = api_client.post("/api/turnos", json=_body(prof, "10:00"))

    assert resp.status_code == 409
    cuerpo = resp.json()
    assert cuerpo["code"] == "hueco_ocupado" and cuerpo["detail"]
    horas = _horas(cuerpo["huecos"])
    assert "10:00" not in horas and "09:30" in horas and "10:30" in horas
    assert cuerpo["huecos"][0] == {
        "inicio": f"{LUNES}T09:00:00-03:00",
        "fin": f"{LUNES}T09:30:00-03:00",
    }
    assert _cuenta(mig_session, Turno) == 1  # solo el primero


def test_409_recalcula_huecos_con_la_misma_duracion(api_client, mig_session: Session):
    prof = _prof(mig_session)
    trat = Tratamiento(nombre="Largo", duracion_min=60)
    mig_session.add(trat)
    mig_session.commit()
    api_client.post("/api/turnos", json=_body(prof, "10:00", tratamiento_id=trat.id))

    resp = api_client.post("/api/turnos", json=_body(prof, "10:30", tratamiento_id=trat.id))

    horas = _horas(resp.json()["huecos"])
    assert resp.status_code == 409
    assert "09:00" in horas and "09:30" not in horas  # 09:30-10:30 pisa 10:00
    assert "11:00" in horas


def test_hueco_dentro_de_bloqueo_activo_409_sin_paciente_ni_auditoria(
    api_client, mig_session: Session
):
    prof = _prof(mig_session)
    mig_session.add(
        Bloqueo(
            profesional_id=prof.id,
            desde=datetime(2030, 3, 4, 9, 0, tzinfo=TZ),
            hasta=datetime(2030, 3, 4, 13, 0, tzinfo=TZ),
            motivo="Sintetico",
        )
    )
    mig_session.commit()

    resp = api_client.post("/api/turnos", json=_body(prof, "10:00"))

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert _horas(resp.json()["huecos"])[0] == "13:00"
    _sin_efectos(mig_session)


def test_rama_exclusion_23p01_tambien_da_409(api_client, mig_session: Session, monkeypatch):
    prof = _prof(mig_session)
    assert api_client.post("/api/turnos", json=_body(prof, "10:00")).status_code == 201
    # Stub del chequeo de aplicacion: nunca ve la ocupacion => la DB decide.
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)

    resp = api_client.post("/api/turnos", json=_body(prof, "10:00"))

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert "10:00" not in _horas(resp.json()["huecos"])
    assert _cuenta(mig_session, Turno) == 1
    assert _cuenta(mig_session, Paciente) == 1  # el paciente de la reserva fallida hizo rollback
    assert _cuenta(mig_session, AuditoriaTurno) == 1


# --- 4.5 reserva autenticada de secretaria --------------------------------------


def _user(session: Session, rol: UserRole) -> User:
    user = User(email=f"{rol.value}-{uuid.uuid4().hex[:6]}@example.test", password_hash="x", rol=rol)
    session.add(user)
    session.commit()
    return user


def _auth(user: User, **kw) -> dict[str, str]:
    token = create_access_token(str(user.id), user.email, user.rol.value, **kw)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def redis_falso():
    with patch("app.core.security.get_redis_client", return_value=fakeredis.FakeRedis()):
        yield


def test_secretaria_reserva_origen_secretaria_created_by(api_client, mig_session: Session):
    prof = _prof(mig_session)
    sec = _user(mig_session, UserRole.SECRETARIA)

    resp = api_client.post("/api/turnos", json=_body(prof), headers=_auth(sec))

    assert resp.status_code == 201, resp.text
    assert resp.json()["origen"] == "secretaria"
    turno = mig_session.get(Turno, uuid.UUID(resp.json()["id"]))
    assert turno.created_by == sec.id
    (aud,) = mig_session.scalars(sa.select(AuditoriaTurno)).all()
    assert aud.actor_tipo.value == "secretaria" and aud.actor_user_id == sec.id


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer token-basura"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},  # esquema no Bearer: nunca degrada a publico
    ],
)
def test_token_invalido_401_sin_turno(api_client, mig_session: Session, headers):
    prof = _prof(mig_session)

    resp = api_client.post("/api/turnos", json=_body(prof), headers=headers)

    assert resp.status_code == 401
    _sin_efectos(mig_session)


def test_token_expirado_401_sin_turno(api_client, mig_session: Session):
    prof = _prof(mig_session)
    sec = _user(mig_session, UserRole.SECRETARIA)

    resp = api_client.post(
        "/api/turnos", json=_body(prof), headers=_auth(sec, expires_delta=timedelta(minutes=-5))
    )

    assert resp.status_code == 401
    _sin_efectos(mig_session)


def test_token_de_odontologo_403_sin_turno(api_client, mig_session: Session):
    prof = _prof(mig_session)
    odo = _user(mig_session, UserRole.ODONTOLOGO)

    resp = api_client.post("/api/turnos", json=_body(prof), headers=_auth(odo))

    assert resp.status_code == 403
    _sin_efectos(mig_session)


def test_sin_header_sigue_siendo_online(api_client, mig_session: Session):
    prof = _prof(mig_session)

    resp = api_client.post("/api/turnos", json=_body(prof))

    assert resp.status_code == 201 and resp.json()["origen"] == "online"
