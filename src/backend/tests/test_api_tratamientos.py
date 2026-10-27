"""C-04 3.2: GET /api/tratamientos (publico, solo activos, solo id/nombre/duracion_min)."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.infrastructure.models import Tratamiento


def test_lista_solo_tratamientos_activos(api_client, mig_session: Session):
    activo = Tratamiento(nombre="Limpieza", duracion_min=30)
    inactivo = Tratamiento(nombre="Viejo", duracion_min=45, is_active=False)
    mig_session.add_all([activo, inactivo])
    mig_session.commit()

    resp = api_client.get("/api/tratamientos")

    assert resp.status_code == 200
    assert resp.json() == [{"id": activo.id, "nombre": "Limpieza", "duracion_min": 30}]


def test_tratamiento_dado_de_baja_logica_excluido(api_client, mig_session: Session):
    baja = Tratamiento(
        nombre="Baja", duracion_min=20, is_active=False, deleted_at=datetime.now(timezone.utc)
    )
    vigente = Tratamiento(nombre="Vigente", duracion_min=20)
    mig_session.add_all([baja, vigente])
    mig_session.commit()

    nombres = [t["nombre"] for t in api_client.get("/api/tratamientos").json()]

    assert nombres == ["Vigente"]


def test_lista_vacia_devuelve_200_y_lista_vacia(api_client):
    resp = api_client.get("/api/tratamientos")

    assert resp.status_code == 200
    assert resp.json() == []


def test_orden_por_nombre(api_client, mig_session: Session):
    mig_session.add_all(
        [
            Tratamiento(nombre="Z-Conducto", duracion_min=60),
            Tratamiento(nombre="A-Consulta", duracion_min=20),
            Tratamiento(nombre="M-Limpieza", duracion_min=30),
        ]
    )
    mig_session.commit()

    nombres = [t["nombre"] for t in api_client.get("/api/tratamientos").json()]

    assert nombres == ["A-Consulta", "M-Limpieza", "Z-Conducto"]


def test_respuesta_sin_campos_de_auditoria(api_client, mig_session: Session):
    mig_session.add(Tratamiento(nombre="Unico", duracion_min=30))
    mig_session.commit()

    (item,) = api_client.get("/api/tratamientos").json()

    assert set(item) == {"id", "nombre", "duracion_min"}


def test_accesible_sin_autenticacion(api_client, mig_session: Session):
    mig_session.add(Tratamiento(nombre="Publico", duracion_min=30))
    mig_session.commit()

    resp = api_client.get("/api/tratamientos")  # sin header Authorization

    assert resp.status_code == 200
