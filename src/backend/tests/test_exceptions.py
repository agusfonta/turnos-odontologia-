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
