"""C-04 3.3: GET /api/disponibilidad (publico; huecos reales con reloj inyectable)."""

import uuid
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import (
    Bloqueo,
    HorarioProfesional,
    Paciente,
    Profesional,
    Tratamiento,
    Turno,
    TurnoOrigen,
)
from app.main import app

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)  # viernes, antes de todo
LUNES = "2030-03-04"  # weekday() == 0
MARTES = "2030-03-05"


@pytest.fixture(autouse=True)
def reloj_fijo():
    # api_client limpia dependency_overrides al terminar el test.
    app.dependency_overrides[get_ahora] = lambda: AHORA
    yield


def _local(fecha: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{fecha}T{hhmm}:00").replace(tzinfo=TZ)


def _prof(session: Session, slot: int = 30, **kw) -> Profesional:
    prof = Profesional(
        nombre="Dra. Sintetica",
        matricula=f"MAT-{uuid.uuid4().hex[:8]}",
        slot_default_min=slot,
        **kw,
    )
    session.add(prof)
    session.flush()
    return prof


def _franja(session: Session, prof, dia: int, ini: time, fin: time, **kw) -> None:
    session.add(
        HorarioProfesional(
            profesional_id=prof.id, dia_semana=dia, hora_inicio=ini, hora_fin=fin, **kw
        )
    )


def _turno(session: Session, prof, fecha: str, ini: str, fin: str, **kw) -> None:
    pac = Paciente(nombre="Paciente Sintetico", telefono="+5491100000000")
    session.add(pac)
    session.flush()
    session.add(
        Turno(
            profesional_id=prof.id,
            paciente_id=pac.id,
            inicio=_local(fecha, ini),
            fin=_local(fecha, fin),
            origen=TurnoOrigen.ONLINE,
            **kw,
        )
    )


def _bloqueo(session: Session, prof, fecha: str, ini: str, fin: str, **kw) -> None:
    session.add(
        Bloqueo(
            profesional_id=prof.id,
            desde=_local(fecha, ini),
            hasta=_local(fecha, fin),
            motivo="Sintetico",
            **kw,
        )
    )


def _get(client, prof, desde: str, hasta: str | None = None, **extra):
    params = {"profesional_id": str(prof.id), "desde": desde, "hasta": hasta or desde, **extra}
    return client.get("/api/disponibilidad", params=params)


def _horas(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [h["inicio"][11:16] for h in resp.json()]


def _franja_dia(session: Session, slot: int = 30, ini=time(9), fin=time(18)) -> Profesional:
    prof = _prof(session, slot)
    _franja(session, prof, 0, ini, fin)
    session.commit()
    return prof


def test_dia_libre_devuelve_huecos_con_offset_clinica(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)

    resp = _get(api_client, prof, LUNES)

    assert resp.status_code == 200
    huecos = resp.json()
    assert len(huecos) == 18
    assert huecos[0] == {"inicio": f"{LUNES}T09:00:00-03:00", "fin": f"{LUNES}T09:30:00-03:00"}
    assert huecos[-1] == {"inicio": f"{LUNES}T17:30:00-03:00", "fin": f"{LUNES}T18:00:00-03:00"}


def test_franjas_manana_y_tarde_sin_huecos_entre_13_y_15(api_client, mig_session: Session):
    prof = _prof(mig_session)
    _franja(mig_session, prof, 0, time(9), time(13))
    _franja(mig_session, prof, 0, time(15), time(19))
    mig_session.commit()

    horas = _horas(_get(api_client, prof, LUNES))

    assert horas[0] == "09:00" and "12:30" in horas and "13:00" not in horas
    assert not any("13:00" <= h < "15:00" for h in horas)
    assert horas[-1] == "18:30" and "15:00" in horas


def test_tratamiento_60_min_ultimo_hueco_de_la_manana_a_las_12(api_client, mig_session: Session):
    prof = _prof(mig_session)
    _franja(mig_session, prof, 0, time(9), time(13))
    _franja(mig_session, prof, 0, time(15), time(19))
    trat = Tratamiento(nombre="Conducto", duracion_min=60)
    mig_session.add(trat)
    mig_session.commit()

    resp = _get(api_client, prof, LUNES, tratamiento_id=trat.id)

    horas = _horas(resp)
    assert "12:00" in horas and "12:30" not in horas
    assert resp.json()[0]["fin"] == f"{LUNES}T10:00:00-03:00"


def test_sin_tratamiento_usa_slot_del_profesional(api_client, mig_session: Session):
    prof = _prof(mig_session, slot=20)
    _franja(mig_session, prof, 0, time(9), time(10))
    mig_session.commit()

    huecos = _get(api_client, prof, LUNES).json()

    assert [h["inicio"][11:16] for h in huecos] == ["09:00", "09:20", "09:40"]
    assert huecos[0]["fin"] == f"{LUNES}T09:20:00-03:00"


def test_profesional_activo_sin_franjas_devuelve_lista_vacia(api_client, mig_session: Session):
    prof = _prof(mig_session)
    mig_session.commit()

    resp = _get(api_client, prof, LUNES)

    assert resp.status_code == 200 and resp.json() == []


def test_dia_sin_franja_no_devuelve_huecos_ese_dia(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)  # solo lunes

    dias = {h["inicio"][:10] for h in _get(api_client, prof, LUNES, MARTES).json()}

    assert dias == {LUNES}


def test_franja_inactiva_no_genera_huecos(api_client, mig_session: Session):
    prof = _prof(mig_session)
    _franja(mig_session, prof, 0, time(9), time(13), is_active=False)
    mig_session.commit()

    assert _get(api_client, prof, LUNES).json() == []


def test_turno_reservado_excluye_el_hueco_y_cancelado_lo_libera(api_client, mig_session: Session):
    prof = _franja_dia(mig_session, fin=time(12))
    _turno(mig_session, prof, LUNES, "10:00", "10:30")
    mig_session.commit()
    horas = _horas(_get(api_client, prof, LUNES))
    assert "10:00" not in horas and "09:30" in horas and "10:30" in horas

    mig_session.query(Turno).update({"estado": EstadoTurno.CANCELADO})
    mig_session.commit()
    assert "10:00" in _horas(_get(api_client, prof, LUNES))


def test_turno_contiguo_no_excluye_vecino_con_tratamiento_largo(api_client, mig_session: Session):
    prof = _franja_dia(mig_session, fin=time(12))
    _turno(mig_session, prof, LUNES, "10:30", "11:00")
    trat = Tratamiento(nombre="Largo", duracion_min=60)
    mig_session.add(trat)
    mig_session.commit()

    horas = _horas(_get(api_client, prof, LUNES, tratamiento_id=trat.id))

    # Semiabierto: 09:30-10:30 es contiguo al turno 10:30-11:00 y SI cabe.
    assert "09:30" in horas
    assert not {"10:00", "10:30"} & set(horas)


def test_bloqueo_activo_excluye_medio_dia_e_inactivo_no(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)
    _bloqueo(mig_session, prof, LUNES, "09:00", "13:00")
    mig_session.commit()
    assert _horas(_get(api_client, prof, LUNES))[0] == "13:00"

    mig_session.query(Bloqueo).update({"is_active": False})
    mig_session.commit()
    assert _horas(_get(api_client, prof, LUNES))[0] == "09:00"


def test_huecos_pasados_excluidos_con_reloj_inyectado(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)
    app.dependency_overrides[get_ahora] = lambda: _local(LUNES, "10:00")

    horas = _horas(_get(api_client, prof, LUNES))

    assert horas[0] == "10:30"  # inicio <= ahora excluido (10:00 tambien)


def test_profesional_inexistente_404(api_client):
    resp = api_client.get(
        "/api/disponibilidad",
        params={"profesional_id": str(uuid.uuid4()), "desde": LUNES, "hasta": LUNES},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == "profesional_no_encontrado"


def test_profesional_inactivo_404(api_client, mig_session: Session):
    prof = _prof(mig_session, is_active=False)
    mig_session.commit()

    assert _get(api_client, prof, LUNES).status_code == 404


def test_tratamiento_inexistente_o_inactivo_404(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)
    inactivo = Tratamiento(nombre="Baja", duracion_min=30, is_active=False)
    mig_session.add(inactivo)
    mig_session.commit()

    sin_existir = _get(api_client, prof, LUNES, tratamiento_id=99999)
    dado_de_baja = _get(api_client, prof, LUNES, tratamiento_id=inactivo.id)

    assert sin_existir.status_code == dado_de_baja.status_code == 404
    assert sin_existir.json()["code"] == "tratamiento_no_encontrado"


def test_hasta_anterior_a_desde_422(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)

    resp = _get(api_client, prof, MARTES, LUNES)

    assert resp.status_code == 422
    assert resp.json()["code"] == "rango_invalido"


def test_rango_mayor_a_31_dias_422_y_31_dias_ok(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)

    assert _get(api_client, prof, "2030-03-04", "2030-04-04").status_code == 422  # 32 dias
    assert _get(api_client, prof, "2030-03-04", "2030-04-03").status_code == 200  # 31 dias


def test_parametros_faltantes_o_mal_formados_422(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)

    assert api_client.get("/api/disponibilidad").status_code == 422
    assert _get(api_client, prof, "no-es-fecha").status_code == 422


def test_accesible_sin_autenticacion(api_client, mig_session: Session):
    prof = _franja_dia(mig_session)

    assert _get(api_client, prof, LUNES).status_code == 200  # sin Authorization
