"""C-04 3.1: GET /api/profesionales (publico, solo activos, sin matricula)."""

import uuid

from sqlalchemy.orm import Session

from app.infrastructure.models import Profesional


def _prof(nombre: str, **kw) -> Profesional:
    return Profesional(
        nombre=nombre, matricula=f"MAT-{uuid.uuid4().hex[:8]}", especialidad="General", **kw
    )


def test_lista_solo_activos(api_client, mig_session: Session):
    activo, inactivo = _prof("Dra. Activa"), _prof("Dr. Inactivo", is_active=False)
    mig_session.add_all([activo, inactivo])
    mig_session.commit()

    resp = api_client.get("/api/profesionales")

    assert resp.status_code == 200
    assert resp.json() == [
        {"id": str(activo.id), "nombre": "Dra. Activa", "especialidad": "General"}
    ]


def test_lista_vacia_devuelve_200_y_lista_vacia(api_client):
    resp = api_client.get("/api/profesionales")

    assert resp.status_code == 200
    assert resp.json() == []


def test_orden_por_nombre(api_client, mig_session: Session):
    mig_session.add_all([_prof("Zeta"), _prof("Alfa"), _prof("Mu")])
    mig_session.commit()

    nombres = [p["nombre"] for p in api_client.get("/api/profesionales").json()]

    assert nombres == ["Alfa", "Mu", "Zeta"]


def test_respuesta_sin_matricula_ni_auditoria(api_client, mig_session: Session):
    mig_session.add(_prof("Dra. Unica"))
    mig_session.commit()

    (item,) = api_client.get("/api/profesionales").json()

    assert set(item) == {"id", "nombre", "especialidad"}


def test_especialidad_nula_se_serializa_como_null(api_client, mig_session: Session):
    mig_session.add(Profesional(nombre="Sin Esp", matricula="MAT-NULL-1"))
    mig_session.commit()

    (item,) = api_client.get("/api/profesionales").json()

    assert item["especialidad"] is None
