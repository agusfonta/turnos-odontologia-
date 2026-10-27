"""Máquina de estados del turno (RN-TU-04). Dominio puro, sin I/O."""

from enum import StrEnum


class EstadoTurno(StrEnum):
    RESERVADO = "reservado"
    CONFIRMADO = "confirmado"
    CANCELADO = "cancelado"
    ATENDIDO = "atendido"
    AUSENTE = "ausente"


class TransicionInvalidaError(ValueError):
    def __init__(self, actual: EstadoTurno, nuevo: EstadoTurno) -> None:
        super().__init__(f"transición inválida: {actual.value} -> {nuevo.value}")
        self.actual = actual
        self.nuevo = nuevo


TRANSICIONES: dict[EstadoTurno, frozenset[EstadoTurno]] = {
    EstadoTurno.RESERVADO: frozenset({EstadoTurno.CONFIRMADO, EstadoTurno.CANCELADO}),
    EstadoTurno.CONFIRMADO: frozenset(
        {EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE, EstadoTurno.CANCELADO}
    ),
    EstadoTurno.CANCELADO: frozenset(),
    EstadoTurno.ATENDIDO: frozenset(),
    EstadoTurno.AUSENTE: frozenset(),
}


def transicionar(actual: EstadoTurno, nuevo: EstadoTurno) -> EstadoTurno:
    if nuevo not in TRANSICIONES[actual]:
        raise TransicionInvalidaError(actual, nuevo)
    return nuevo
