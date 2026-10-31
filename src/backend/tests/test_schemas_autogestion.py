"""C-07 4.1: schemas publicos de autogestion por token (D4). Guarda anti-fuga de campos."""

import uuid

import pytest
from pydantic import ValidationError

from app.domain.schemas import (
    TurnoPorTokenDetalle,
    TurnoPorTokenOut,
    TurnoReprogramarPublico,
)

INICIO = "2030-03-04T10:00:00-03:00"
FIN = "2030-03-04T10:30:00-03:00"

CAMPOS_OUT = {"inicio", "fin", "estado", "profesional_id", "tratamiento_id", "gestionable_hasta"}


def _out(**extra) -> dict:
    return {
        "inicio": INICIO,
        "fin": FIN,
        "estado": "reservado",
        "profesional_id": str(uuid.uuid4()),
        "tratamiento_id": 1,
        "gestionable_hasta": "2030-03-03T10:00:00-03:00",
        **extra,
    }


def _detalle(**extra) -> dict:
    base = {"profesional_nombre": "Dra. Sintetica", "tratamiento_nombre": "Limpieza"}
    return _out(**{**base, **extra})


def test_reprogramar_publico_acepta_solo_inicio_aware():
    assert TurnoReprogramarPublico(inicio=INICIO).inicio.utcoffset() is not None


@pytest.mark.parametrize(
    "body",
    [
        {"inicio": INICIO, "sobreturno": True},
        {"inicio": INICIO, "sobreturno": False},
        {"inicio": INICIO, "paciente_id": str(uuid.uuid4())},
        {"inicio": "2030-03-04T10:00:00"},  # naive
        {},
    ],
)
def test_reprogramar_publico_rechaza_extras_y_naive(body):
    with pytest.raises(ValidationError):
        TurnoReprogramarPublico(**body)


def test_conjunto_de_campos_es_exactamente_el_publico():
    assert set(TurnoPorTokenOut.model_fields) == CAMPOS_OUT
    assert set(TurnoPorTokenDetalle.model_fields) == CAMPOS_OUT | {
        "profesional_nombre",
        "tratamiento_nombre",
    }


@pytest.mark.parametrize("estado", ["reservado", "confirmado", "cancelado", "atendido", "ausente"])
def test_out_acepta_los_cinco_estados(estado):
    assert TurnoPorTokenOut(**_out(estado=estado)).estado == estado


def test_out_y_detalle_aceptan_tratamiento_nulo():
    assert TurnoPorTokenOut(**_out(tratamiento_id=None)).tratamiento_id is None
    d = TurnoPorTokenDetalle(**_detalle(tratamiento_id=None, tratamiento_nombre=None))
    assert (d.tratamiento_id, d.tratamiento_nombre) == (None, None)


@pytest.mark.parametrize("campo", ["paciente_id", "id", "token_publico"])
def test_out_y_detalle_rechazan_campos_de_fuga_como_extra(campo):
    with pytest.raises(ValidationError):
        TurnoPorTokenOut(**_out(**{campo: "x"}))
    with pytest.raises(ValidationError):
        TurnoPorTokenDetalle(**_detalle(**{campo: "x"}))
