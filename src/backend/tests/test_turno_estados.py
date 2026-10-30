"""Tarea 1.1: máquina de estados del turno (RN-TU-04). Dominio puro, sin DB."""

import itertools

import pytest

from app.domain.turno_estados import (
    TRANSICIONES,
    EstadoTurno,
    TransicionInvalidaError,
    transicionar,
)

VALIDAS = [
    (EstadoTurno.RESERVADO, EstadoTurno.CONFIRMADO),
    (EstadoTurno.CONFIRMADO, EstadoTurno.ATENDIDO),
    (EstadoTurno.CONFIRMADO, EstadoTurno.AUSENTE),
    (EstadoTurno.RESERVADO, EstadoTurno.CANCELADO),
    (EstadoTurno.CONFIRMADO, EstadoTurno.CANCELADO),
]
INVALIDAS = [p for p in itertools.product(EstadoTurno, EstadoTurno) if p not in VALIDAS]


def test_reservado_a_confirmado_valido():
    assert transicionar(EstadoTurno.RESERVADO, EstadoTurno.CONFIRMADO) is EstadoTurno.CONFIRMADO


def test_reservado_a_atendido_rechazado():
    with pytest.raises(TransicionInvalidaError):
        transicionar(EstadoTurno.RESERVADO, EstadoTurno.ATENDIDO)


@pytest.mark.parametrize(("actual", "nuevo"), VALIDAS)
def test_las_5_transiciones_validas_se_aceptan(actual, nuevo):
    assert transicionar(actual, nuevo) is nuevo


@pytest.mark.parametrize(("actual", "nuevo"), INVALIDAS)
def test_toda_otra_transicion_se_rechaza(actual, nuevo):
    with pytest.raises(TransicionInvalidaError):
        transicionar(actual, nuevo)


def test_reservado_a_ausente_rechazado():
    with pytest.raises(TransicionInvalidaError):
        transicionar(EstadoTurno.RESERVADO, EstadoTurno.AUSENTE)


@pytest.mark.parametrize(
    "terminal", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE]
)
def test_estados_terminales_no_transicionan(terminal):
    for destino in EstadoTurno:
        with pytest.raises(TransicionInvalidaError):
            transicionar(terminal, destino)


def test_son_exactamente_5_transiciones_validas():
    assert len(VALIDAS) == 5
    assert len(INVALIDAS) == len(EstadoTurno) ** 2 - 5


# --- C-05 2.1: reprogramar como regla propia (D6, DD-07) ---------------------

from app.domain.turno_estados import estado_tras_reprogramar  # noqa: E402


def test_reprogramar_confirmado_vuelve_a_reservado():
    assert estado_tras_reprogramar(EstadoTurno.CONFIRMADO) is EstadoTurno.RESERVADO


def test_reprogramar_reservado_sigue_reservado():
    assert estado_tras_reprogramar(EstadoTurno.RESERVADO) is EstadoTurno.RESERVADO


@pytest.mark.parametrize(
    "terminal", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE]
)
def test_reprogramar_terminal_lanza_transicion_invalida(terminal):
    with pytest.raises(TransicionInvalidaError) as exc:
        estado_tras_reprogramar(terminal)
    assert exc.value.actual is terminal and exc.value.nuevo is EstadoTurno.RESERVADO


def test_confirmado_a_reservado_sigue_rechazado_por_transicionar():
    with pytest.raises(TransicionInvalidaError):
        transicionar(EstadoTurno.CONFIRMADO, EstadoTurno.RESERVADO)
    assert EstadoTurno.RESERVADO not in TRANSICIONES[EstadoTurno.CONFIRMADO]
