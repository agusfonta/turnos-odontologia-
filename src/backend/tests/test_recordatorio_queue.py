"""C-04 5.1: RecordatorioQueue (ZADD post-commit, tolerante a fallas) con fakeredis + PG real."""

import logging
import uuid
from datetime import datetime, time, timedelta, timezone

import fakeredis
import pytest
import redis
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.clock import get_ahora
from app.infrastructure.jobs import (
    RECORDATORIOS_KEY,
    RecordatorioQueue,
    get_recordatorio_queue,
)
from app.infrastructure.models import HorarioProfesional, Profesional, Turno
from app.infrastructure.unit_of_work import get_uow_factory
from app.main import app

AHORA = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
LUNES = "2030-03-04"


class RedisCaido:
    """Cliente que simula Redis caido: cuenta los intentos de ZADD."""

    def __init__(self) -> None:
        self.intentos = 0

    def zadd(self, *args, **kwargs):
        self.intentos += 1
        raise redis.ConnectionError("redis caido (simulado)")


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def entorno(api_client, mig_session: Session, fake_redis):
    app.dependency_overrides[get_ahora] = lambda: AHORA
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        fake_redis, sleep=lambda _s: None
    )
    prof = Profesional(nombre="Dra. Sintetica", matricula=f"MAT-{uuid.uuid4().hex[:8]}")
    mig_session.add(prof)
    mig_session.flush()
    mig_session.add(
        HorarioProfesional(profesional_id=prof.id, dia_semana=0, hora_inicio=time(9), hora_fin=time(18))
    )
    mig_session.commit()
    return api_client, prof, mig_session


def _reservar(client, prof, hhmm="10:00"):
    return client.post(
        "/api/turnos",
        json={
            "profesional_id": str(prof.id),
            "inicio": f"{LUNES}T{hhmm}:00-03:00",
            "paciente_nombre": "Paciente Sintetico",
            "paciente_telefono": "+5491100000000",
        },
    )


def test_reserva_encola_job_con_turno_id_y_score(entorno, fake_redis):
    client, prof, _ = entorno

    resp = _reservar(client, prof)

    assert resp.status_code == 201
    inicio = datetime.fromisoformat(resp.json()["inicio"])
    esperado = (inicio - timedelta(hours=24)).timestamp()
    assert fake_redis.zrange(RECORDATORIOS_KEY, 0, -1, withscores=True) == [
        (resp.json()["id"], esperado)
    ]


def test_clave_del_job_es_jobs_recordatorios():
    assert RECORDATORIOS_KEY == "jobs:recordatorios"


def test_redis_caido_igual_201_turno_persistido_y_warning(entorno, caplog):
    client, prof, session = entorno
    caido = RedisCaido()
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        caido, sleep=lambda _s: None
    )

    with caplog.at_level(logging.WARNING):
        resp = _reservar(client, prof)

    assert resp.status_code == 201
    assert caido.intentos == 3  # reintento acotado
    session.expire_all()
    assert session.scalar(sa.select(sa.func.count()).select_from(Turno)) == 1
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(resp.json()["id"] in r.getMessage() for r in avisos)


def test_reintenta_y_se_recupera_si_redis_vuelve(fake_redis):
    class Intermitente:
        def __init__(self) -> None:
            self.llamadas = 0

        def zadd(self, *args, **kwargs):
            self.llamadas += 1
            if self.llamadas < 3:
                raise redis.ConnectionError("intermitente")
            return fake_redis.zadd(*args, **kwargs)

    cliente = Intermitente()
    esperas: list[float] = []
    cola = RecordatorioQueue(cliente, sleep=esperas.append)
    turno_id = uuid.uuid4()

    assert cola.encolar(turno_id, AHORA + timedelta(days=3)) is True
    assert cliente.llamadas == 3
    assert esperas == [0.05, 0.1]  # backoff corto
    assert fake_redis.zscore(RECORDATORIOS_KEY, str(turno_id)) is not None


def test_conflicto_404_422_no_encolan(entorno, fake_redis):
    client, prof, _ = entorno
    assert _reservar(client, prof, "10:00").status_code == 201
    fake_redis.delete(RECORDATORIOS_KEY)

    assert _reservar(client, prof, "10:00").status_code == 409
    assert _reservar(client, prof, "10:10").status_code == 422
    ajeno = type("P", (), {"id": uuid.uuid4()})()
    assert _reservar(client, ajeno).status_code == 404

    assert fake_redis.zcard(RECORDATORIOS_KEY) == 0


def test_reencolar_el_mismo_turno_no_duplica(fake_redis):
    cola = RecordatorioQueue(fake_redis, sleep=lambda _s: None)
    turno_id = uuid.uuid4()
    inicio = AHORA + timedelta(days=3)

    cola.encolar(turno_id, inicio)
    cola.encolar(turno_id, inicio)

    assert fake_redis.zcard(RECORDATORIOS_KEY) == 1


def test_miembro_es_solo_el_turno_id_sin_datos_personales(fake_redis):
    cola = RecordatorioQueue(fake_redis, sleep=lambda _s: None)
    turno_id = uuid.uuid4()

    cola.encolar(turno_id, AHORA + timedelta(days=3))

    assert fake_redis.zrange(RECORDATORIOS_KEY, 0, -1) == [str(turno_id)]


def test_encola_despues_del_commit(entorno, mig_engine):
    """C-04b D3: al encolar, el turno ya es visible desde OTRA conexion; orden commit -> encolar."""
    from tests.support import factoria_espia

    client, prof, _ = entorno
    bitacora: list[str] = []
    visto_al_encolar: list[bool] = []

    class ColaEspia:
        def encolar(self, turno_id, inicio):
            bitacora.append("encolar")
            with mig_engine.connect() as otra:  # conexion nueva: solo ve lo confirmado
                visto_al_encolar.append(
                    otra.scalar(sa.select(sa.func.count()).select_from(Turno).where(Turno.id == turno_id))
                    == 1
                )
            return True

    app.dependency_overrides[get_uow_factory] = lambda: factoria_espia(mig_engine, bitacora)
    app.dependency_overrides[get_recordatorio_queue] = lambda: ColaEspia()

    resp = _reservar(client, prof)

    assert resp.status_code == 201
    assert bitacora == ["enter", "commit", "close", "encolar"]
    assert visto_al_encolar == [True]
