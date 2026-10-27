"""C-04 4.4: anti-solape bajo concurrencia real (PG real, threads + Barrier, sin locks)."""

import threading
import uuid
from datetime import datetime, time, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.infrastructure.models import AuditoriaTurno, HorarioProfesional, Paciente, Profesional, Turno
from app.main import app

AHORA = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
LUNES = "2030-03-04"
ITERACIONES = 10


@pytest.fixture
def prof(api_client, mig_session: Session) -> Profesional:
    # api_client: override de get_db sobre la DB clonada; reloj fijo.
    app.dependency_overrides[get_ahora] = lambda: AHORA
    p = Profesional(nombre="Dra. Sintetica", matricula=f"MAT-{uuid.uuid4().hex[:8]}")
    mig_session.add(p)
    mig_session.flush()
    mig_session.add(
        HorarioProfesional(profesional_id=p.id, dia_semana=0, hora_inicio=time(9), hora_fin=time(18))
    )
    mig_session.commit()
    return p


def _reservar_en_paralelo(prof_id: uuid.UUID, hhmm: str, hilos: int) -> list[int]:
    """Lanza `hilos` POST simultaneos al mismo hueco (Barrier) y devuelve los status."""
    barrera = threading.Barrier(hilos)
    statuses: list[int] = [0] * hilos
    errores: list[BaseException] = []

    def trabajar(i: int) -> None:
        try:
            client = TestClient(app)  # un cliente (y una sesion por request) por hilo
            barrera.wait(timeout=10)
            resp = client.post(
                "/api/turnos",
                json={
                    "profesional_id": str(prof_id),
                    "inicio": f"{LUNES}T{hhmm}:00-03:00",
                    "paciente_nombre": f"Paciente Sintetico {i}",
                    "paciente_telefono": f"+54911000000{i:02d}",
                },
            )
            statuses[i] = resp.status_code
        except BaseException as exc:  # noqa: BLE001 - se re-lanza en el hilo principal
            errores.append(exc)

    hilos_ = [threading.Thread(target=trabajar, args=(i,)) for i in range(hilos)]
    for h in hilos_:
        h.start()
    for h in hilos_:
        h.join(timeout=30)
    assert not errores, errores
    assert 0 not in statuses, "un hilo no termino"
    return statuses


def _cuenta(session: Session, modelo) -> int:
    session.expire_all()
    return session.scalar(sa.select(sa.func.count()).select_from(modelo))


def test_dos_reservas_simultaneas_una_201_una_409(prof, mig_session: Session):
    for i in range(ITERACIONES):  # sin flakiness: 10 slots distintos, mismo patron
        hhmm = f"{9 + i // 2:02d}:{'00' if i % 2 == 0 else '30'}"
        statuses = _reservar_en_paralelo(prof.id, hhmm, hilos=2)
        assert sorted(statuses) == [201, 409], (hhmm, statuses)

    assert _cuenta(mig_session, Turno) == ITERACIONES  # exactamente 1 por horario
    assert _cuenta(mig_session, AuditoriaTurno) == ITERACIONES
    assert _cuenta(mig_session, Paciente) == ITERACIONES  # los perdedores hicieron rollback


def test_cinco_reservas_simultaneas_una_201_cuatro_409(prof, mig_session: Session):
    for i in range(ITERACIONES):
        hhmm = f"{9 + i // 2:02d}:{'00' if i % 2 == 0 else '30'}"
        statuses = _reservar_en_paralelo(prof.id, hhmm, hilos=5)
        assert sorted(statuses) == [201, 409, 409, 409, 409], (hhmm, statuses)

    assert _cuenta(mig_session, Turno) == ITERACIONES
    inicios = mig_session.scalars(sa.select(Turno.inicio)).all()
    assert len(set(inicios)) == ITERACIONES  # un unico turno por horario


def test_sin_chequeo_de_aplicacion_la_constraint_sola_garantiza_un_ganador(
    prof, mig_session: Session, monkeypatch
):
    """Fuerza la carrera real: el check de app nunca ve la ocupacion, decide la DB."""
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)

    for i in range(ITERACIONES):
        hhmm = f"{9 + i // 2:02d}:{'00' if i % 2 == 0 else '30'}"
        statuses = _reservar_en_paralelo(prof.id, hhmm, hilos=5)
        assert sorted(statuses) == [201, 409, 409, 409, 409], (hhmm, statuses)

    assert _cuenta(mig_session, Turno) == ITERACIONES
