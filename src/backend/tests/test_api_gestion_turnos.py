"""C-05 6.x: POST /api/turnos/manual, PATCH y DELETE /api/turnos/{id} (PG real, TestClient)."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import fakeredis
import pytest
import redis
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.jobs import RECORDATORIOS_KEY, RecordatorioQueue, get_recordatorio_queue
from app.infrastructure.models import (
    AuditoriaTurno,
    Bloqueo,
    Paciente,
    Profesional,
    Turno,
    User,
    UserRole,
)
from app.infrastructure.unit_of_work import get_uow_factory
from app.main import app
from tests.support import factoria_espia
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


@pytest.fixture(autouse=True)
def entorno_fijo():
    app.dependency_overrides[get_ahora] = lambda: AHORA
    with patch("app.core.security.get_redis_client", return_value=fakeredis.FakeRedis()):
        yield


@pytest.fixture
def fake_redis(api_client) -> fakeredis.FakeRedis:
    r = fakeredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        r, sleep=lambda _s: None
    )
    return r


@pytest.fixture
def prof(api_client, mig_session: Session) -> Profesional:
    return crear_profesional(mig_session)


@pytest.fixture
def sec(api_client, mig_session: Session) -> User:
    return crear_secretaria(mig_session)


def _auth(user: User, **kw) -> dict[str, str]:
    token = create_access_token(str(user.id), user.email, user.rol.value, **kw)
    return {"Authorization": f"Bearer {token}"}


def _odontologo(session: Session) -> User:
    user = User(email=f"odo-{uuid.uuid4().hex[:6]}@example.test", password_hash="x", rol=UserRole.ODONTOLOGO)
    session.add(user)
    session.commit()
    return user


def _manual_body(prof, hhmm: str = "10:00", **extra) -> dict:
    return {
        "profesional_id": str(prof.id),
        "inicio": f"{LUNES}T{hhmm}:00-03:00",
        "paciente_nombre": "Paciente Manual",
        "paciente_telefono": "+5491100000001",
        **extra,
    }


def _jobs(r) -> dict[str, float]:
    return dict(r.zrange(RECORDATORIOS_KEY, 0, -1, withscores=True))


def _score(hhmm: str, dia: str = LUNES) -> float:
    return (inicio(hhmm, dia) - timedelta(hours=24)).timestamp()


# --- 6.1 POST /api/turnos/manual ---------------------------------------------------------


def test_alta_manual_201(api_client, mig_session, prof, sec, fake_redis):
    resp = api_client.post("/api/turnos/manual", json=_manual_body(prof), headers=_auth(sec))

    assert resp.status_code == 201, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == {
        "id", "profesional_id", "paciente_id", "tratamiento_id", "inicio", "fin",
        "estado", "origen", "sobreturno", "token_publico",
    }
    assert (cuerpo["estado"], cuerpo["origen"], cuerpo["sobreturno"]) == ("reservado", "secretaria", False)
    assert cuerpo["inicio"].endswith("-03:00")
    mig_session.expire_all()
    turno = mig_session.get(Turno, uuid.UUID(cuerpo["id"]))
    assert turno.created_by == sec.id and str(turno.paciente_id) == cuerpo["paciente_id"]
    assert _jobs(fake_redis) == {cuerpo["id"]: _score("10:00")}  # encolado post-commit


def test_alta_manual_reutiliza_paciente_existente(api_client, mig_session, prof, sec, fake_redis):
    previo = Paciente(nombre="Nombre Original", telefono="+5491100000001")
    mig_session.add(previo)
    mig_session.commit()

    resp = api_client.post(
        "/api/turnos/manual", json=_manual_body(prof, paciente_nombre="Otro"), headers=_auth(sec)
    )

    assert resp.status_code == 201
    assert resp.json()["paciente_id"] == str(previo.id)
    assert cuenta(mig_session, Paciente) == 1
    mig_session.refresh(previo)
    assert previo.nombre == "Nombre Original"


def test_alta_manual_con_sobreturno_coexiste(api_client, mig_session, prof, sec, fake_redis):
    crear_turno(mig_session, prof, "10:00")

    resp = api_client.post(
        "/api/turnos/manual", json=_manual_body(prof, sobreturno=True), headers=_auth(sec)
    )

    assert resp.status_code == 201 and resp.json()["sobreturno"] is True
    assert cuenta(mig_session, Turno) == 2


def test_alta_manual_sin_token_o_invalido_401_sin_filas(api_client, mig_session, prof):
    for headers in ({}, {"Authorization": "Bearer token-basura"}):
        assert api_client.post("/api/turnos/manual", json=_manual_body(prof), headers=headers).status_code == 401
    assert cuenta(mig_session, Turno) == 0 and cuenta(mig_session, Paciente) == 0


def test_alta_manual_odontologo_403_sin_filas(api_client, mig_session, prof):
    odo = _odontologo(mig_session)

    resp = api_client.post("/api/turnos/manual", json=_manual_body(prof), headers=_auth(odo))

    assert resp.status_code == 403
    assert cuenta(mig_session, Turno) == 0 and cuenta(mig_session, Paciente) == 0


def test_alta_manual_409_con_huecos_y_sin_job(api_client, mig_session, prof, sec, fake_redis):
    crear_turno(mig_session, prof, "10:00")

    resp = api_client.post("/api/turnos/manual", json=_manual_body(prof), headers=_auth(sec))

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert resp.json()["huecos"]
    assert _jobs(fake_redis) == {}
    assert cuenta(mig_session, Paciente) == 1  # solo el previo del fixture de turno


def test_alta_manual_sobreturno_dentro_de_bloqueo_409(api_client, mig_session, prof, sec, fake_redis):
    mig_session.add(
        Bloqueo(profesional_id=prof.id, desde=inicio("09:00"), hasta=inicio("12:00"), motivo="Congreso")
    )
    mig_session.commit()

    resp = api_client.post(
        "/api/turnos/manual", json=_manual_body(prof, sobreturno=True), headers=_auth(sec)
    )

    assert resp.status_code == 409
    assert cuenta(mig_session, Turno) == 0 and _jobs(fake_redis) == {}


@pytest.mark.parametrize(
    "cambios",
    [
        {"estado": "confirmado"},
        {"inicio": f"{LUNES}T10:00:00"},
        {"paciente_telefono": "1155550000"},
        {"inicio": f"{LUNES}T10:10:00-03:00"},  # fuera de grilla
    ],
)
def test_alta_manual_422_sin_filas_ni_job(api_client, mig_session, prof, sec, fake_redis, cambios):
    resp = api_client.post(
        "/api/turnos/manual", json=_manual_body(prof, **cambios), headers=_auth(sec)
    )

    assert resp.status_code == 422
    assert cuenta(mig_session, Turno) == 0 and cuenta(mig_session, Paciente) == 0
    assert _jobs(fake_redis) == {}


def test_alta_manual_profesional_inexistente_404(api_client, mig_session, prof, sec):
    body = _manual_body(prof)
    body["profesional_id"] = str(uuid.uuid4())
    assert api_client.post("/api/turnos/manual", json=body, headers=_auth(sec)).status_code == 404


def test_sobreturno_en_la_reserva_publica_sigue_en_422(api_client, mig_session, prof):
    resp = api_client.post("/api/turnos", json=_manual_body(prof, sobreturno=True))
    assert resp.status_code == 422 and cuenta(mig_session, Turno) == 0


# --- 6.2 DELETE /api/turnos/{id} ---------------------------------------------------------


def test_cancelar_200_y_desencola(api_client, mig_session, prof, sec, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    RecordatorioQueue(fake_redis).encolar(turno.id, inicio("10:00"))
    RecordatorioQueue(fake_redis).encolar(uuid.uuid4(), inicio("11:00"))

    resp = api_client.delete(f"/api/turnos/{turno.id}", headers=_auth(sec))

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["estado"] == "cancelado" and cuerpo["id"] == str(turno.id)
    assert "token_publico" not in cuerpo
    assert str(turno.id) not in _jobs(fake_redis) and len(_jobs(fake_redis)) == 1
    assert len(auditorias(mig_session, turno.id, "cancelar")) == 1


@pytest.mark.parametrize("metodo", ["delete", "patch"])
def test_gestion_sin_token_401_y_odontologo_403(api_client, mig_session, prof, metodo):
    turno = crear_turno(mig_session, prof, "10:00")
    odo = _odontologo(mig_session)
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}
    llamar = getattr(api_client, metodo)

    assert llamar(f"/api/turnos/{turno.id}", **kw).status_code == 401
    assert llamar(f"/api/turnos/{turno.id}", headers={"Authorization": "Bearer basura"}, **kw).status_code == 401
    assert llamar(f"/api/turnos/{turno.id}", headers=_auth(odo), **kw).status_code == 403

    mig_session.expire_all()
    fila = mig_session.get(Turno, turno.id)
    assert (fila.estado, fila.inicio) == (EstadoTurno.RESERVADO, inicio("10:00"))


@pytest.mark.parametrize("metodo", ["delete", "patch"])
def test_gestion_turno_inexistente_404(api_client, sec, fake_redis, metodo):
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}

    resp = getattr(api_client, metodo)(f"/api/turnos/{uuid.uuid4()}", headers=_auth(sec), **kw)

    assert resp.status_code == 404 and resp.json()["code"] == "turno_no_encontrado"
    assert _jobs(fake_redis) == {}


@pytest.mark.parametrize("metodo", ["delete", "patch"])
def test_gestion_uuid_invalido_422(api_client, sec, metodo):
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}
    assert getattr(api_client, metodo)("/api/turnos/no-es-uuid", headers=_auth(sec), **kw).status_code == 422


@pytest.mark.parametrize("metodo", ["delete", "patch"])
@pytest.mark.parametrize("estado", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE])
def test_gestion_terminal_422_transicion_no_permitida(
    api_client, mig_session, prof, sec, fake_redis, metodo, estado
):
    turno = crear_turno(mig_session, prof, "10:00", estado=estado)
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}
    antes = dict(_jobs(fake_redis))

    resp = getattr(api_client, metodo)(f"/api/turnos/{turno.id}", headers=_auth(sec), **kw)

    assert resp.status_code == 422
    assert resp.json() == {
        "detail": "La transición de estado no está permitida",
        "code": "transicion_no_permitida",
        "estado_actual": estado.value,
    }
    assert auditorias(mig_session, turno.id) == [] and _jobs(fake_redis) == antes


@pytest.mark.parametrize("metodo", ["delete", "patch"])
def test_gestion_turno_ya_iniciado_422_anticipacion(
    api_client, mig_session, prof, sec, fake_redis, metodo
):
    turno = crear_turno(mig_session, prof, "10:00", dia="2030-02-25")  # anterior a AHORA
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}

    resp = getattr(api_client, metodo)(f"/api/turnos/{turno.id}", headers=_auth(sec), **kw)

    assert resp.status_code == 422 and resp.json()["code"] == "anticipacion_insuficiente"
    assert resp.json()["min_horas"] == 24
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).estado is EstadoTurno.RESERVADO
    assert _jobs(fake_redis) == {}


class _RedisCaido:
    def __init__(self) -> None:
        self.intentos = 0

    def zadd(self, *a, **k):
        self.intentos += 1
        raise redis.ConnectionError("caido (simulado)")

    zrem = zadd


def test_cancelar_con_redis_caido_200_y_warning(api_client, mig_session, prof, sec, caplog):
    turno = crear_turno(mig_session, prof, "10:00")
    caido = _RedisCaido()
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        caido, sleep=lambda _s: None
    )

    with caplog.at_level(logging.WARNING):
        resp = api_client.delete(f"/api/turnos/{turno.id}", headers=_auth(sec))

    assert resp.status_code == 200 and caido.intentos == 3
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).estado is EstadoTurno.CANCELADO
    assert any(str(turno.id) in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


# --- 6.3 PATCH /api/turnos/{id} ----------------------------------------------------------


def _patch(api_client, turno, user, hhmm: str, **extra):
    return api_client.patch(
        f"/api/turnos/{turno.id}",
        json={"inicio": f"{LUNES}T{hhmm}:00-03:00", **extra},
        headers=_auth(user),
    )


def test_reprogramar_200_y_reencola(api_client, mig_session, prof, sec, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    RecordatorioQueue(fake_redis).encolar(turno.id, inicio("10:00"))

    resp = _patch(api_client, turno, sec, "14:00")

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["inicio"] == f"{LUNES}T14:00:00-03:00" and cuerpo["fin"] == f"{LUNES}T14:30:00-03:00"
    assert (cuerpo["estado"], cuerpo["profesional_id"]) == ("reservado", str(prof.id))
    assert "token_publico" not in cuerpo
    assert _jobs(fake_redis) == {str(turno.id): _score("14:00")}  # un unico job, score nuevo


def test_reprogramar_confirmado_queda_reservado(api_client, mig_session, prof, sec, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)

    assert _patch(api_client, turno, sec, "14:00").json()["estado"] == "reservado"


def test_reprogramar_libera_el_horario_anterior(api_client, mig_session, prof, sec, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    def horas():
        huecos = api_client.get(
            "/api/disponibilidad",
            params={"profesional_id": str(prof.id), "desde": LUNES, "hasta": LUNES},
        ).json()
        return {h["inicio"][11:16] for h in huecos}

    assert "10:00" not in horas() and "14:00" in horas()
    _patch(api_client, turno, sec, "14:00")
    assert "10:00" in horas() and "14:00" not in horas()


def test_reprogramar_409_con_huecos_y_sin_tocar_la_cola(api_client, mig_session, prof, sec, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000097")
    RecordatorioQueue(fake_redis).encolar(turno.id, inicio("10:00"))
    antes = dict(_jobs(fake_redis))

    resp = _patch(api_client, turno, sec, "14:00")

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert resp.json()["huecos"] and "14:00" not in {h["inicio"][11:16] for h in resp.json()["huecos"]}
    assert _jobs(fake_redis) == antes
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("10:00")
    assert auditorias(mig_session, turno.id) == []


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"inicio": f"{LUNES}T14:00:00"},  # naive
        {"inicio": f"{LUNES}T14:10:00-03:00"},  # fuera de grilla
        {"inicio": "2030-02-25T14:00:00-03:00"},  # lunes anterior a AHORA
        {"inicio": f"{LUNES}T14:00:00-03:00", "profesional_id": str(uuid.uuid4())},
        {},
    ],
)
def test_reprogramar_422(api_client, mig_session, prof, sec, fake_redis, cuerpo):
    turno = crear_turno(mig_session, prof, "10:00")

    resp = api_client.patch(f"/api/turnos/{turno.id}", json=cuerpo, headers=_auth(sec))

    assert resp.status_code == 422
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("10:00")
    assert _jobs(fake_redis) == {}


def test_reprogramar_audita_el_detalle_completo(api_client, mig_session, prof, sec, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)

    _patch(api_client, turno, sec, "14:00")

    (aud,) = auditorias(mig_session, turno.id, "reprogramar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("secretaria", sec.id)
    assert aud.detalle == {
        "inicio_anterior": "2030-03-04T13:00:00+00:00",
        "fin_anterior": "2030-03-04T13:30:00+00:00",
        "inicio_nuevo": "2030-03-04T17:00:00+00:00",
        "fin_nuevo": "2030-03-04T17:30:00+00:00",
        "estado_anterior": "confirmado",
        "estado_nuevo": "reservado",
        "sobreturno": False,
        "exento_anticipacion": False,
    }


def test_reprogramar_con_redis_caido_200_y_warning(api_client, mig_session, prof, sec, caplog):
    turno = crear_turno(mig_session, prof, "10:00")
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        _RedisCaido(), sleep=lambda _s: None
    )

    with caplog.at_level(logging.WARNING):
        resp = _patch(api_client, turno, sec, "14:00")

    assert resp.status_code == 200
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("14:00")
    assert any(str(turno.id) in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


# --- 6.4 orden commit -> efecto -------------------------------------------------------------


class _ColaVerificadora:
    """Cola fake que, al ser llamada, lee desde OTRA conexion si el cambio ya es visible."""

    def __init__(self, engine, bitacora: list[str], turno_id, esperado: dict) -> None:
        self._engine, self._bitacora = engine, bitacora
        self._turno_id, self._esperado = turno_id, esperado
        self.visto: dict | None = None

    def _leer(self) -> dict:
        with Session(self._engine) as otra:
            fila = otra.get(Turno, self._turno_id)
            return {"estado": fila.estado, "inicio": fila.inicio}

    def encolar(self, turno_id, inicio) -> bool:
        self._bitacora.append("encolar")
        self.visto = self._leer()
        return True

    def cancelar(self, turno_id) -> bool:
        self._bitacora.append("cancelar")
        self.visto = self._leer()
        return True


def _con_espia(mig_engine, bitacora, cola, *, commit_error=None):
    app.dependency_overrides[get_uow_factory] = lambda: factoria_espia(
        mig_engine, bitacora, commit_error=commit_error
    )
    app.dependency_overrides[get_recordatorio_queue] = lambda: cola


def test_patch_commit_antes_de_encolar(api_client, mig_engine, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    bitacora: list[str] = []
    cola = _ColaVerificadora(mig_engine, bitacora, turno.id, {})
    _con_espia(mig_engine, bitacora, cola)

    assert _patch(api_client, turno, sec, "14:00").status_code == 200

    assert bitacora == ["enter", "commit", "close", "encolar"]
    assert cola.visto["inicio"] == inicio("14:00")  # el cambio ya era visible desde otra conexion


def test_delete_commit_antes_de_desencolar(api_client, mig_engine, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    bitacora: list[str] = []
    cola = _ColaVerificadora(mig_engine, bitacora, turno.id, {})
    _con_espia(mig_engine, bitacora, cola)

    assert api_client.delete(f"/api/turnos/{turno.id}", headers=_auth(sec)).status_code == 200

    assert bitacora == ["enter", "commit", "close", "cancelar"]
    assert cola.visto["estado"] is EstadoTurno.CANCELADO


@pytest.mark.parametrize("metodo", ["patch", "delete"])
def test_commit_fallido_500_sin_auditoria_y_cola_sin_tocar(
    mig_engine, mig_session, prof, sec, metodo, api_client
):
    from fastapi.testclient import TestClient

    turno = crear_turno(mig_session, prof, "10:00")
    bitacora: list[str] = []
    cola = _ColaVerificadora(mig_engine, bitacora, turno.id, {})
    _con_espia(
        mig_engine, bitacora, cola,
        commit_error=OperationalError("COMMIT", {}, Exception("conexion perdida (simulada)")),
    )
    cliente = TestClient(app, raise_server_exceptions=False)
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}

    resp = getattr(cliente, metodo)(f"/api/turnos/{turno.id}", headers=_auth(sec), **kw)

    assert resp.status_code == 500
    assert "encolar" not in bitacora and "cancelar" not in bitacora and cola.visto is None
    assert auditorias(mig_session, turno.id) == []
    mig_session.expire_all()
    fila = mig_session.get(Turno, turno.id)
    assert (fila.estado, fila.inicio) == (EstadoTurno.RESERVADO, inicio("10:00"))
    assert cuenta(mig_session, AuditoriaTurno) == 0


# --- C-07 6.6 POST /api/turnos/{id}/confirmar (secretaria) ------------------------------------


def test_secretaria_confirma_200(api_client, mig_session, prof, sec, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")

    resp = api_client.post(f"/api/turnos/{turno.id}/confirmar", headers=_auth(sec))

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["estado"] == "confirmado" and cuerpo["id"] == str(turno.id)
    assert "token_publico" not in cuerpo
    (aud,) = auditorias(mig_session, turno.id, "confirmar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("secretaria", sec.id)
    assert _jobs(fake_redis) == {}  # confirmar no toca la cola


def test_secretaria_reconfirma_200_sin_auditoria_nueva(api_client, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    for _ in range(2):
        assert api_client.post(f"/api/turnos/{turno.id}/confirmar", headers=_auth(sec)).status_code == 200

    assert len(auditorias(mig_session, turno.id, "confirmar")) == 1


def test_confirmar_sin_token_401_y_odontologo_403_sin_cambios(api_client, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")
    odo = _odontologo(mig_session)
    url = f"/api/turnos/{turno.id}/confirmar"

    assert api_client.post(url).status_code == 401
    assert api_client.post(url, headers={"Authorization": "Bearer basura"}).status_code == 401
    assert api_client.post(url, headers=_auth(odo)).status_code == 403

    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).estado is EstadoTurno.RESERVADO
    assert auditorias(mig_session, turno.id) == []


def test_confirmar_inexistente_404_y_uuid_invalido_422(api_client, sec):
    r404 = api_client.post(f"/api/turnos/{uuid.uuid4()}/confirmar", headers=_auth(sec))
    assert r404.status_code == 404 and r404.json()["code"] == "turno_no_encontrado"
    assert api_client.post("/api/turnos/no-es-uuid/confirmar", headers=_auth(sec)).status_code == 422


@pytest.mark.parametrize("estado", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE])
def test_secretaria_confirmar_terminal_422(api_client, mig_session, prof, sec, estado):
    turno = crear_turno(mig_session, prof, "10:00", estado=estado)

    resp = api_client.post(f"/api/turnos/{turno.id}/confirmar", headers=_auth(sec))

    assert resp.status_code == 422 and resp.json()["code"] == "transicion_no_permitida"
    assert auditorias(mig_session, turno.id) == []
