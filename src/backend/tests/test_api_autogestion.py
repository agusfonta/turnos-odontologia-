"""C-07 6.x: rutas publicas por token (GET/POST confirmar/PATCH/DELETE) con PG real y TestClient."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import fakeredis
import pytest
import redis
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.core.settings import get_settings
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.jobs import RECORDATORIOS_KEY, RecordatorioQueue, get_recordatorio_queue
from app.infrastructure.models import AuditoriaTurno, Profesional, Tratamiento, Turno
from app.infrastructure.unit_of_work import get_uow_factory
from app.main import app
from tests.support import factoria_espia
from tests.support_gestion import (
    AHORA,
    LUNES,
    auditorias,
    crear_profesional,
    crear_turno,
    cuenta,
    inicio,
)

BASE = "/api/turnos/por-token"
CAMPOS_GET = {
    "inicio", "fin", "estado", "profesional_id", "tratamiento_id", "gestionable_hasta",
    "profesional_nombre", "tratamiento_nombre",
}
CAMPOS_OUT = CAMPOS_GET - {"profesional_nombre", "tratamiento_nombre"}


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


def _jobs(r) -> dict[str, float]:
    return dict(r.zrange(RECORDATORIOS_KEY, 0, -1, withscores=True))


def _score(hhmm: str, dia: str = LUNES) -> float:
    return (inicio(hhmm, dia) - timedelta(hours=24)).timestamp()


def _url(turno, sufijo: str = "") -> str:
    return f"{BASE}/{turno.token_publico}{sufijo}"


def _patch(api_client, turno, hhmm: str, **extra):
    return api_client.patch(_url(turno), json={"inicio": f"{LUNES}T{hhmm}:00-03:00", **extra})


class _RedisCaido:
    def __init__(self) -> None:
        self.intentos = 0

    def zadd(self, *a, **k):
        self.intentos += 1
        raise redis.ConnectionError("caido (simulado)")

    zrem = zadd


# --- 6.1 GET ----------------------------------------------------------------------------


def test_get_por_token_200_sin_datos_del_paciente(api_client, mig_session, prof):
    trat = Tratamiento(nombre="Limpieza Sintetica", duracion_min=30)
    mig_session.add(trat)
    mig_session.commit()
    turno = crear_turno(mig_session, prof, "10:00")
    turno.tratamiento_id = trat.id
    mig_session.commit()

    resp = api_client.get(_url(turno))  # sin Authorization

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == CAMPOS_GET
    assert cuerpo["estado"] == "reservado"
    assert cuerpo["profesional_id"] == str(prof.id) and cuerpo["profesional_nombre"] == prof.nombre
    assert (cuerpo["tratamiento_id"], cuerpo["tratamiento_nombre"]) == (trat.id, "Limpieza Sintetica")
    for ausente in ("paciente_id", "id", "token_publico", "origen", "sobreturno"):
        assert ausente not in cuerpo
    texto = resp.text
    assert "Paciente Previo" not in texto and "+5491100000099" not in texto
    assert turno.token_publico not in texto and str(turno.id) not in texto


def test_get_por_token_fechas_con_offset_de_la_clinica(api_client, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    cuerpo = api_client.get(_url(turno)).json()

    assert cuerpo["inicio"] == "2030-03-04T10:00:00-03:00"
    assert cuerpo["fin"] == "2030-03-04T10:30:00-03:00"
    assert cuerpo["gestionable_hasta"] == "2030-03-03T10:00:00-03:00"


def test_get_por_token_turno_sin_tratamiento_devuelve_nulos(api_client, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    cuerpo = api_client.get(_url(turno)).json()

    assert (cuerpo["tratamiento_id"], cuerpo["tratamiento_nombre"]) == (None, None)


@pytest.mark.parametrize("estado", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO])
def test_get_por_token_de_turno_terminal_responde_200_con_su_estado(
    api_client, mig_session, prof, estado
):
    turno = crear_turno(mig_session, prof, "10:00", estado=estado)

    resp = api_client.get(_url(turno))

    assert resp.status_code == 200 and resp.json()["estado"] == estado.value


def test_get_por_token_no_audita(api_client, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")
    api_client.get(_url(turno))
    assert cuenta(mig_session, AuditoriaTurno) == 0


# --- 6.2 404 uniforme -------------------------------------------------------------------

TOKENS_INVALIDOS = [
    "a" * 43,  # inexistente
    "a" * 65,  # demasiado largo
    "con$signo",  # caracter no URL-safe
    "con%20espacio",
    "con%25porcentaje",
    "con.punto",
    "con%2Fbarra",
]
RUTAS = [("get", ""), ("post", "/confirmar"), ("patch", ""), ("delete", "")]


def _llamar(api_client, metodo: str, token: str, sufijo: str):
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}
    return getattr(api_client, metodo)(f"{BASE}/{token}{sufijo}", **kw)


@pytest.mark.parametrize("metodo,sufijo", RUTAS)
@pytest.mark.parametrize("token", TOKENS_INVALIDOS)
def test_token_invalido_404_uniforme_y_sin_efectos(
    api_client, mig_session, prof, fake_redis, metodo, sufijo, token
):
    turno = crear_turno(mig_session, prof, "10:00")
    referencia = _llamar(api_client, "get", "b" * 43, "")

    resp = _llamar(api_client, metodo, token, sufijo)

    assert resp.status_code == 404, resp.text  # nunca 422
    assert resp.json()["code"] == "turno_no_encontrado"
    assert resp.content == referencia.content  # cuerpo identico entre causas y entre rutas
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).estado is EstadoTurno.RESERVADO
    assert cuenta(mig_session, AuditoriaTurno) == 0
    assert _jobs(fake_redis) == {}


def test_los_logs_de_la_app_no_contienen_el_token(api_client, mig_session, prof, fake_redis, caplog):
    turno = crear_turno(mig_session, prof, "10:00")
    token = turno.token_publico
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        _RedisCaido(), sleep=lambda _s: None
    )

    with caplog.at_level(logging.DEBUG):
        api_client.get(_url(turno))
        api_client.post(_url(turno, "/confirmar"))
        _patch(api_client, turno, "14:00")
        api_client.delete(_url(turno))
        for malo in ("x" * 43, "mal$token"):
            api_client.get(f"{BASE}/{malo}")

    propios = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    for registro in propios:
        mensaje = registro.getMessage()
        assert token not in mensaje and "x" * 43 not in mensaje and "mal$token" not in mensaje
        assert token not in str(registro.args)


# --- 6.3 confirmar ----------------------------------------------------------------------


def test_confirmar_por_token_200(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")

    resp = api_client.post(_url(turno, "/confirmar"))

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == CAMPOS_OUT and cuerpo["estado"] == "confirmado"
    (aud,) = auditorias(mig_session, turno.id, "confirmar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).token_publico == turno.token_publico


def test_reconfirmar_200_sin_auditoria_nueva(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")

    primera = api_client.post(_url(turno, "/confirmar"))
    segunda = api_client.post(_url(turno, "/confirmar"))

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert segunda.json() == primera.json()
    assert len(auditorias(mig_session, turno.id, "confirmar")) == 1


@pytest.mark.parametrize("estado", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE])
def test_confirmar_terminal_422_transicion_no_permitida(api_client, mig_session, prof, estado):
    turno = crear_turno(mig_session, prof, "10:00", estado=estado)

    resp = api_client.post(_url(turno, "/confirmar"))

    assert resp.status_code == 422 and resp.json()["code"] == "transicion_no_permitida"
    assert resp.json()["estado_actual"] == estado.value
    assert auditorias(mig_session, turno.id) == []


def test_confirmar_turno_ya_iniciado_422_anticipacion(api_client, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00", dia="2030-02-25")  # anterior a AHORA

    resp = api_client.post(_url(turno, "/confirmar"))

    assert resp.status_code == 422 and resp.json()["code"] == "anticipacion_insuficiente"
    assert resp.json()["min_horas"] == 0
    assert _estado(mig_session, turno) is EstadoTurno.RESERVADO


def test_confirmar_dentro_de_la_ventana_200(api_client, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00", dia="2030-03-01")  # 1 h despues de AHORA

    assert api_client.post(_url(turno, "/confirmar")).status_code == 200


def test_confirmar_no_toca_la_cola(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    RecordatorioQueue(fake_redis).encolar(turno.id, inicio("10:00"))
    antes = _jobs(fake_redis)

    assert api_client.post(_url(turno, "/confirmar")).status_code == 200

    assert _jobs(fake_redis) == antes == {str(turno.id): _score("10:00")}


def _estado(session: Session, turno) -> EstadoTurno:
    session.expire_all()
    return session.get(Turno, turno.id).estado


# --- 6.4 DELETE -------------------------------------------------------------------------


def test_cancelar_por_token_200_y_desencola(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    RecordatorioQueue(fake_redis).encolar(turno.id, inicio("10:00"))
    RecordatorioQueue(fake_redis).encolar(uuid.uuid4(), inicio("11:00"))

    resp = api_client.delete(_url(turno))

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == CAMPOS_OUT and cuerpo["estado"] == "cancelado"
    assert str(turno.id) not in _jobs(fake_redis) and len(_jobs(fake_redis)) == 1
    (aud,) = auditorias(mig_session, turno.id, "cancelar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)


def test_cancelar_fuera_de_plazo_422_con_min_horas_y_cola_intacta(
    api_client, mig_session, prof, fake_redis
):
    turno = crear_turno(mig_session, prof, "10:00", dia="2030-03-01")  # 1 h despues de AHORA
    RecordatorioQueue(fake_redis).encolar(turno.id, inicio("10:00", "2030-03-01"))
    antes = _jobs(fake_redis)

    resp = api_client.delete(_url(turno))

    assert resp.status_code == 422 and resp.json()["code"] == "anticipacion_insuficiente"
    assert resp.json()["min_horas"] == 24
    assert _jobs(fake_redis) == antes
    assert _estado(mig_session, turno) is EstadoTurno.RESERVADO


def test_cancelar_terminal_422_y_cola_intacta(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.ATENDIDO)

    resp = api_client.delete(_url(turno))

    assert resp.status_code == 422 and resp.json()["code"] == "transicion_no_permitida"
    assert auditorias(mig_session, turno.id) == []


def test_el_horario_cancelado_vuelve_a_la_disponibilidad(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    params = {"profesional_id": str(prof.id), "desde": LUNES, "hasta": LUNES}

    def horas() -> set[str]:
        return {h["inicio"][11:16] for h in api_client.get("/api/disponibilidad", params=params).json()}

    assert "10:00" not in horas()
    assert api_client.delete(_url(turno)).status_code == 200
    assert "10:00" in horas()


def test_cancel_min_hours_configurable_permite_cancelar_a_4_horas(
    api_client, mig_session, prof, fake_redis, monkeypatch
):
    turno = crear_turno(mig_session, prof, "13:00", dia="2030-03-01")  # 16:00 UTC; AHORA 12:00 UTC
    monkeypatch.setenv("CANCEL_MIN_HOURS", "3")
    get_settings.cache_clear()
    try:
        resp = api_client.delete(_url(turno))
    finally:
        get_settings.cache_clear()

    assert resp.status_code == 200 and resp.json()["estado"] == "cancelado"


def test_cancelar_con_redis_caido_200_y_warning_sin_token(api_client, mig_session, prof, caplog):
    turno = crear_turno(mig_session, prof, "10:00")
    caido = _RedisCaido()
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        caido, sleep=lambda _s: None
    )

    with caplog.at_level(logging.WARNING):
        resp = api_client.delete(_url(turno))

    assert resp.status_code == 200 and caido.intentos == 3
    assert _estado(mig_session, turno) is EstadoTurno.CANCELADO
    avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(str(turno.id) in a for a in avisos)
    assert all(turno.token_publico not in a for a in avisos)


# --- 6.5 PATCH --------------------------------------------------------------------------


def test_reprogramar_por_token_200_y_reencola(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    RecordatorioQueue(fake_redis).encolar(turno.id, inicio("10:00"))

    resp = _patch(api_client, turno, "14:00")

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == CAMPOS_OUT
    assert cuerpo["inicio"] == "2030-03-04T14:00:00-03:00" and cuerpo["estado"] == "reservado"
    assert _jobs(fake_redis) == {str(turno.id): _score("14:00")}


def test_reprogramar_confirmado_queda_reservado(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)

    resp = _patch(api_client, turno, "14:00")

    assert resp.status_code == 200 and resp.json()["estado"] == "reservado"


def test_reprogramar_con_sobreturno_en_el_body_422(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")

    resp = _patch(api_client, turno, "14:00", sobreturno=True)

    assert resp.status_code == 422
    assert _estado(mig_session, turno) is EstadoTurno.RESERVADO
    assert _jobs(fake_redis) == {}


def test_reprogramar_409_con_huecos_y_turno_intacto(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00")
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000002")

    resp = _patch(api_client, turno, "14:00")

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert resp.json()["huecos"]
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("10:00")
    assert _jobs(fake_redis) == {} and auditorias(mig_session, turno.id) == []


def test_reprogramar_fuera_de_plazo_422(api_client, mig_session, prof, fake_redis):
    turno = crear_turno(mig_session, prof, "10:00", dia="2030-03-01")

    resp = _patch(api_client, turno, "14:00")

    assert resp.status_code == 422 and resp.json()["code"] == "anticipacion_insuficiente"
    assert _jobs(fake_redis) == {}


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"inicio": "2030-03-04T14:00:00"},  # naive
        {"inicio": f"{LUNES}T14:10:00-03:00"},  # fuera de grilla
        {"inicio": "2030-02-25T14:00:00-03:00"},  # pasado
        {"inicio": f"{LUNES}T14:00:00-03:00", "paciente_id": str(uuid.uuid4())},
        {},
    ],
)
def test_reprogramar_inicio_invalido_422(api_client, mig_session, prof, fake_redis, cuerpo):
    turno = crear_turno(mig_session, prof, "10:00")

    resp = api_client.patch(_url(turno), json=cuerpo)

    assert resp.status_code == 422
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("10:00")
    assert _jobs(fake_redis) == {}


def test_reprogramar_audita_actor_paciente_y_la_consulta_ve_el_horario_nuevo(
    api_client, mig_session, prof, fake_redis
):
    turno = crear_turno(mig_session, prof, "10:00")

    assert _patch(api_client, turno, "14:00").status_code == 200

    (aud,) = auditorias(mig_session, turno.id, "reprogramar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)
    assert aud.detalle["exento_anticipacion"] is False and aud.detalle["sobreturno"] is False
    assert api_client.get(_url(turno)).json()["inicio"] == "2030-03-04T14:00:00-03:00"


def test_reprogramar_con_redis_caido_200_y_warning(api_client, mig_session, prof, caplog):
    turno = crear_turno(mig_session, prof, "10:00")
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        _RedisCaido(), sleep=lambda _s: None
    )

    with caplog.at_level(logging.WARNING):
        resp = _patch(api_client, turno, "14:00")

    assert resp.status_code == 200
    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("14:00")
    assert any(str(turno.id) in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


# --- 6.7 orden commit -> efecto -----------------------------------------------------------


class _ColaVerificadora:
    """Cola fake que, al ser llamada, lee desde OTRA conexion si el cambio ya es visible."""

    def __init__(self, engine, bitacora: list[str], turno_id) -> None:
        self._engine, self._bitacora, self._turno_id = engine, bitacora, turno_id
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


def _con_espia(mig_engine, bitacora, cola):
    app.dependency_overrides[get_uow_factory] = lambda: factoria_espia(mig_engine, bitacora)
    app.dependency_overrides[get_recordatorio_queue] = lambda: cola


def test_patch_por_token_commit_antes_de_encolar(api_client, mig_engine, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")
    bitacora: list[str] = []
    cola = _ColaVerificadora(mig_engine, bitacora, turno.id)
    _con_espia(mig_engine, bitacora, cola)

    assert _patch(api_client, turno, "14:00").status_code == 200

    # 1ra UoW: resolver el token (lectura); 2da: el caso de uso con su commit; luego el efecto.
    assert bitacora[-4:] == ["enter", "commit", "close", "encolar"]
    assert cola.visto["inicio"] == inicio("14:00")  # ya visible desde otra conexion


def test_delete_por_token_commit_antes_de_desencolar(api_client, mig_engine, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")
    bitacora: list[str] = []
    cola = _ColaVerificadora(mig_engine, bitacora, turno.id)
    _con_espia(mig_engine, bitacora, cola)

    assert api_client.delete(_url(turno)).status_code == 200

    assert bitacora[-4:] == ["enter", "commit", "close", "cancelar"]
    assert cola.visto["estado"] is EstadoTurno.CANCELADO


@pytest.mark.parametrize(
    "metodo,caso",
    [("patch", "404"), ("patch", "409"), ("patch", "422"), ("delete", "404"), ("delete", "422")],
)
def test_errores_por_token_no_tocan_la_cola(api_client, mig_engine, mig_session, prof, metodo, caso):
    turno = crear_turno(mig_session, prof, "10:00", dia="2030-03-01" if caso == "422" else LUNES)
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000002")
    bitacora: list[str] = []
    cola = _ColaVerificadora(mig_engine, bitacora, turno.id)
    _con_espia(mig_engine, bitacora, cola)
    token = "z" * 43 if caso == "404" else turno.token_publico
    kw = {"json": {"inicio": f"{LUNES}T14:00:00-03:00"}} if metodo == "patch" else {}

    resp = getattr(api_client, metodo)(f"{BASE}/{token}", **kw)

    assert resp.status_code == int(caso)
    assert "encolar" not in bitacora and "cancelar" not in bitacora and cola.visto is None
