"""C-06 6.2/6.3: GET /api/agenda (PG real, TestClient)."""

import uuid
from unittest.mock import patch

import fakeredis
import pytest
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.core.security import create_access_token
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import (
    Bloqueo,
    Paciente,
    Profesional,
    Tratamiento,
    Turno,
    TurnoOrigen,
    User,
    UserRole,
)
from app.main import app
from tests.support_gestion import (
    AHORA,
    LUNES,
    crear_profesional,
    crear_secretaria,
    crear_turno,
    inicio,
)

MIERCOLES = "2030-03-06"
DOMINGO = "2030-03-10"
LUNES_SIGUIENTE = "2030-03-11"


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


def _odontologo(session: Session, vinculado_a: Profesional | None = None) -> User:
    user = User(
        email=f"odo-{uuid.uuid4().hex[:6]}@example.test", password_hash="x", rol=UserRole.ODONTOLOGO
    )
    session.add(user)
    session.flush()
    if vinculado_a is not None:
        vinculado_a.user_id = user.id
    session.commit()
    return user


def _get(api_client, user, prof=None, **params):
    if prof is not None:
        params.setdefault("profesional_id", str(prof.id))
    return api_client.get("/api/agenda", params=params, headers=_auth(user) if user else {})


def _horas(cuerpo) -> list[str]:
    return [t["inicio"][11:16] for t in cuerpo["turnos"]]


# --- 6.2 consulta de secretaria --------------------------------------------------------------


def test_secretaria_vista_dia(api_client, mig_session, prof, sec):
    crear_turno(mig_session, prof, "10:00", telefono="+5491100000011")
    crear_turno(mig_session, prof, "09:00", telefono="+5491100000012")

    resp = _get(api_client, sec, prof, dia=LUNES)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == {"profesional", "vista", "desde", "hasta", "turnos", "bloqueos"}
    assert cuerpo["profesional"] == {"id": str(prof.id), "nombre": prof.nombre}
    assert (cuerpo["vista"], cuerpo["desde"], cuerpo["hasta"]) == ("dia", LUNES, LUNES)
    assert _horas(cuerpo) == ["09:00", "10:00"]  # ordenados por inicio
    assert cuerpo["turnos"][0]["inicio"].endswith("-03:00")  # offset de la clinica


def test_vista_dia_es_el_default(api_client, mig_session, prof, sec):
    resp = _get(api_client, sec, prof, dia=LUNES)
    assert resp.json()["vista"] == "dia"


def test_vista_semana_lunes_a_domingo_sin_la_semana_siguiente(api_client, mig_session, prof, sec):
    crear_turno(mig_session, prof, "10:00", telefono="+5491100000011", dia=LUNES)
    crear_turno(mig_session, prof, "10:00", telefono="+5491100000012", dia=DOMINGO)
    crear_turno(mig_session, prof, "10:00", telefono="+5491100000013", dia=LUNES_SIGUIENTE)
    crear_turno(mig_session, prof, "10:00", telefono="+5491100000014", dia="2030-03-03")  # domingo previo

    resp = _get(api_client, sec, prof, dia=MIERCOLES, vista="semana")

    cuerpo = resp.json()
    assert (cuerpo["vista"], cuerpo["desde"], cuerpo["hasta"]) == ("semana", LUNES, DOMINGO)
    assert [t["inicio"][:10] for t in cuerpo["turnos"]] == [LUNES, DOMINGO]


def test_limites_del_dia_en_la_zona_de_la_clinica(api_client, mig_session, prof, sec):
    crear_turno(mig_session, prof, "23:30", minutos=30, dia="2030-03-03", telefono="+5491100000011")
    crear_turno(mig_session, prof, "00:00", dia=LUNES, telefono="+5491100000012")

    cuerpo = _get(api_client, sec, prof, dia=LUNES).json()

    assert _horas(cuerpo) == ["00:00"]  # el de las 23:30 (termina a las 00:00) no es de este dia


def test_turno_que_cruza_la_medianoche_aparece_en_ambos_dias(api_client, mig_session, prof, sec):
    crear_turno(mig_session, prof, "23:45", minutos=30, dia="2030-03-03", telefono="+5491100000011")

    assert len(_get(api_client, sec, prof, dia=LUNES).json()["turnos"]) == 1
    assert len(_get(api_client, sec, prof, dia="2030-03-03").json()["turnos"]) == 1
    assert _get(api_client, sec, prof, dia="2030-03-02").json()["turnos"] == []


def test_estados_y_origen_distinguidos_incluye_cancelado(api_client, mig_session, prof, sec):
    crear_turno(mig_session, prof, "09:00", telefono="+5491100000011")  # reservado online
    crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO, telefono="+5491100000012")
    crear_turno(mig_session, prof, "11:00", estado=EstadoTurno.CANCELADO, telefono="+5491100000013")
    pac = Paciente(nombre="Paciente Mostrador", telefono="+5491100000014")
    mig_session.add(pac)
    mig_session.flush()
    mig_session.add(
        Turno(
            profesional_id=prof.id, paciente_id=pac.id, inicio=inicio("12:00"), fin=inicio("12:30"),
            estado=EstadoTurno.RESERVADO, origen=TurnoOrigen.SECRETARIA, sobreturno=True,
        )
    )
    mig_session.commit()

    turnos = _get(api_client, sec, prof, dia=LUNES).json()["turnos"]

    assert [(t["estado"], t["origen"], t["sobreturno"]) for t in turnos] == [
        ("reservado", "online", False),
        ("confirmado", "online", False),
        ("cancelado", "online", False),
        ("reservado", "secretaria", True),
    ]


def test_paciente_y_tratamiento_presente_o_nulo(api_client, mig_session, prof, sec):
    trat = Tratamiento(nombre=f"Limpieza-{uuid.uuid4().hex[:6]}", duracion_min=30)
    mig_session.add(trat)
    mig_session.flush()
    pac = Paciente(nombre="Paciente Con Tratamiento", telefono="+5491100000015")
    mig_session.add(pac)
    mig_session.flush()
    mig_session.add(
        Turno(
            profesional_id=prof.id, paciente_id=pac.id, tratamiento_id=trat.id,
            inicio=inicio("10:00"), fin=inicio("10:30"), origen=TurnoOrigen.ONLINE,
        )
    )
    mig_session.commit()
    crear_turno(mig_session, prof, "09:00", telefono="+5491100000016")

    sin, con = _get(api_client, sec, prof, dia=LUNES).json()["turnos"]

    assert sin["tratamiento"] is None
    assert con["tratamiento"] == {"id": trat.id, "nombre": trat.nombre}
    assert con["paciente"] == {
        "id": str(pac.id), "nombre": "Paciente Con Tratamiento", "telefono": "+5491100000015",
    }
    assert set(sin["paciente"]) == {"id", "nombre", "telefono"}


def test_sin_token_publico_en_ninguna_respuesta(api_client, mig_session, prof, sec):
    crear_turno(mig_session, prof, "09:00", telefono="+5491100000011")
    crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CANCELADO, telefono="+5491100000012")

    resp = _get(api_client, sec, prof, dia=LUNES, vista="semana")

    assert "token_publico" not in resp.text


def test_bloqueos_activos_incluidos_e_inactivos_no(api_client, mig_session, prof, sec):
    mig_session.add_all(
        [
            Bloqueo(profesional_id=prof.id, desde=inicio("14:00"), hasta=inicio("18:00"), motivo="Congreso"),
            Bloqueo(profesional_id=prof.id, desde=inicio("09:00"), hasta=inicio("10:00"), motivo="Baja", is_active=False),
            Bloqueo(profesional_id=prof.id, desde=inicio("11:00", "2030-03-12"), hasta=inicio("12:00", "2030-03-12"), motivo="Otro dia"),
        ]
    )
    mig_session.commit()

    cuerpo = _get(api_client, sec, prof, dia=LUNES).json()

    assert len(cuerpo["bloqueos"]) == 1
    b = cuerpo["bloqueos"][0]
    assert set(b) == {"id", "desde", "hasta", "motivo"}
    assert (b["motivo"], b["desde"], b["hasta"]) == (
        "Congreso", f"{LUNES}T14:00:00-03:00", f"{LUNES}T18:00:00-03:00",
    )


@pytest.mark.parametrize(
    "params",
    [{}, {"dia": "no-es-fecha"}, {"dia": LUNES, "vista": "mes"}, {"dia": "2030-02-30"}],
)
def test_parametros_invalidos_422(api_client, mig_session, prof, sec, params):
    assert _get(api_client, sec, prof, **params).status_code == 422


def test_profesional_inexistente_404_e_inactivo_200(api_client, mig_session, prof, sec):
    resp = _get(api_client, sec, None, dia=LUNES, profesional_id=str(uuid.uuid4()))
    assert resp.status_code == 404 and resp.json()["code"] == "profesional_no_encontrado"

    crear_turno(mig_session, prof, "09:00", telefono="+5491100000011")
    prof.is_active = False
    mig_session.commit()
    inactivo = _get(api_client, sec, prof, dia=LUNES)
    assert inactivo.status_code == 200 and len(inactivo.json()["turnos"]) == 1  # historica


def test_sin_token_o_invalido_401(api_client, mig_session, prof):
    assert _get(api_client, None, prof, dia=LUNES).status_code == 401
    resp = api_client.get(
        "/api/agenda",
        params={"dia": LUNES, "profesional_id": str(prof.id)},
        headers={"Authorization": "Bearer basura"},
    )
    assert resp.status_code == 401


# --- 6.3 aislamiento por rol -----------------------------------------------------------------


def test_odontologo_ve_solo_su_agenda(api_client, mig_session, prof, sec):
    otro = crear_profesional(mig_session)
    odo = _odontologo(mig_session, vinculado_a=prof)
    crear_turno(mig_session, prof, "09:00", telefono="+5491100000011")
    crear_turno(mig_session, otro, "10:00", telefono="+5491100000012")
    mig_session.add(
        Bloqueo(profesional_id=otro.id, desde=inicio("14:00"), hasta=inicio("15:00"), motivo="Ajeno")
    )
    mig_session.commit()

    resp = _get(api_client, odo, None, dia=LUNES)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["profesional"]["id"] == str(prof.id)
    assert _horas(cuerpo) == ["09:00"] and cuerpo["bloqueos"] == []


def test_odontologo_con_su_propio_profesional_explicito_200(api_client, mig_session, prof):
    odo = _odontologo(mig_session, vinculado_a=prof)

    assert _get(api_client, odo, prof, dia=LUNES).status_code == 200


def test_odontologo_con_profesional_ajeno_403_agenda_ajena(api_client, mig_session, prof):
    otro = crear_profesional(mig_session)
    odo = _odontologo(mig_session, vinculado_a=prof)
    crear_turno(mig_session, otro, "10:00", telefono="+5491100000012")

    resp = _get(api_client, odo, otro, dia=LUNES)

    assert resp.status_code == 403 and resp.json()["code"] == "agenda_ajena"
    assert "turnos" not in resp.json()


def test_odontologo_con_id_inexistente_tambien_403_no_404(api_client, mig_session, prof):
    odo = _odontologo(mig_session, vinculado_a=prof)

    resp = _get(api_client, odo, None, dia=LUNES, profesional_id=str(uuid.uuid4()))

    assert resp.status_code == 403 and resp.json()["code"] == "agenda_ajena"


def test_odontologo_sin_vinculo_403(api_client, mig_session, prof):
    odo = _odontologo(mig_session)

    resp = _get(api_client, odo, None, dia=LUNES)
    assert resp.status_code == 403 and resp.json()["code"] == "sin_profesional_asociado"
    resp = _get(api_client, odo, prof, dia=LUNES)  # tampoco con profesional explicito
    assert resp.status_code == 403 and resp.json()["code"] == "sin_profesional_asociado"


def test_secretaria_sin_profesional_422(api_client, mig_session, prof, sec):
    resp = _get(api_client, sec, None, dia=LUNES)

    assert resp.status_code == 422 and resp.json()["code"] == "profesional_requerido"


def test_secretaria_ve_cada_profesional_con_lo_suyo(api_client, mig_session, prof, sec):
    otro = crear_profesional(mig_session)
    crear_turno(mig_session, prof, "09:00", telefono="+5491100000011")
    crear_turno(mig_session, otro, "10:00", telefono="+5491100000012")
    mig_session.add(
        Bloqueo(profesional_id=otro.id, desde=inicio("14:00"), hasta=inicio("15:00"), motivo="Del otro")
    )
    mig_session.commit()

    a = _get(api_client, sec, prof, dia=LUNES).json()
    b = _get(api_client, sec, otro, dia=LUNES).json()

    assert (_horas(a), a["bloqueos"]) == (["09:00"], [])
    assert _horas(b) == ["10:00"] and [x["motivo"] for x in b["bloqueos"]] == ["Del otro"]
