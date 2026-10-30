"""C-05 3.1: errores nuevos de turnos (D8) a traves del handler global."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AnticipacionInsuficienteError,
    NotFoundError,
    TransicionNoPermitidaError,
    TurnoNoEncontradoError,
    register_exception_handlers,
)


def _respuesta(exc: Exception):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise exc

    return TestClient(app).get("/boom")


@pytest.mark.parametrize(
    ("exc", "status", "cuerpo"),
    [
        (
            TurnoNoEncontradoError(),
            404,
            {"detail": "Turno no encontrado", "code": "turno_no_encontrado"},
        ),
        (
            TransicionNoPermitidaError("atendido"),
            422,
            {
                "detail": "La transición de estado no está permitida",
                "code": "transicion_no_permitida",
                "estado_actual": "atendido",
            },
        ),
        (
            AnticipacionInsuficienteError(24),
            422,
            {
                "detail": "No se cumple la anticipación mínima",
                "code": "anticipacion_insuficiente",
                "min_horas": 24,
            },
        ),
    ],
)
def test_errores_de_turnos_responden_status_code_y_extra(exc, status, cuerpo):
    resp = _respuesta(exc)
    assert resp.status_code == status
    assert resp.json() == cuerpo


def test_turno_no_encontrado_es_not_found():
    assert isinstance(TurnoNoEncontradoError(), NotFoundError)


def test_extra_de_transicion_y_anticipacion_distintos_valores():
    assert TransicionNoPermitidaError("cancelado").extra() == {"estado_actual": "cancelado"}
    assert AnticipacionInsuficienteError(3).extra() == {"min_horas": 3}


# --- C-06 3.3: errores de bloqueos y agenda (D7) ------------------------------------------

from app.domain.agenda import TurnoEnConflicto  # noqa: E402
from app.domain.turno_estados import EstadoTurno  # noqa: E402
from app.core.exceptions import (  # noqa: E402
    AgendaAjenaError,
    BloqueoConTurnosError,
    BloqueoNoEncontradoError,
    ProfesionalRequeridoError,
    SinProfesionalAsociadoError,
)


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (BloqueoNoEncontradoError(), 404, "bloqueo_no_encontrado"),
        (SinProfesionalAsociadoError(), 403, "sin_profesional_asociado"),
        (AgendaAjenaError(), 403, "agenda_ajena"),
        (ProfesionalRequeridoError(), 422, "profesional_requerido"),
    ],
)
def test_errores_de_bloqueos_y_agenda_status_y_code(exc, status, code):
    resp = _respuesta(exc)
    assert resp.status_code == status
    assert resp.json()["code"] == code
    assert resp.json()["detail"]


def test_bloqueo_no_encontrado_es_not_found():
    assert issubclass(BloqueoNoEncontradoError, NotFoundError)


def test_bloqueo_con_turnos_409_con_lista_en_iso_con_offset():
    from datetime import datetime, timedelta, timezone
    import uuid

    tz = timezone(timedelta(hours=-3))
    tid = uuid.uuid4()
    exc = BloqueoConTurnosError(
        [
            TurnoEnConflicto(
                id=tid,
                inicio=datetime(2030, 3, 4, 10, 0, tzinfo=tz),
                fin=datetime(2030, 3, 4, 10, 30, tzinfo=tz),
                estado=EstadoTurno.RESERVADO,
            )
        ]
    )
    resp = _respuesta(exc)
    assert resp.status_code == 409
    cuerpo = resp.json()
    assert cuerpo["code"] == "bloqueo_con_turnos"
    assert cuerpo["turnos"] == [
        {
            "id": str(tid),
            "inicio": "2030-03-04T10:00:00-03:00",
            "fin": "2030-03-04T10:30:00-03:00",
            "estado": "reservado",
        }
    ]
    assert set(cuerpo) == {"detail", "code", "turnos"}


def test_bloqueo_con_turnos_lista_vacia_y_varios():
    assert BloqueoConTurnosError([]).extra() == {"turnos": []}
