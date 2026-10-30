"""C-05 4.1: schemas de gestion de secretaria (D9). Strict, sin campos fantasma."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.schemas import (
    TurnoCreate,
    TurnoGestionadoOut,
    TurnoManualCreado,
    TurnoManualCreate,
    TurnoReprogramar,
)

INICIO = "2030-03-04T10:00:00-03:00"


def _manual(**extra) -> dict:
    return {
        "profesional_id": str(uuid.uuid4()),
        "inicio": INICIO,
        "paciente_nombre": "Paciente Sintetico",
        "paciente_telefono": "+5491100000000",
        **extra,
    }


def test_manual_acepta_sobreturno_con_default_false():
    assert TurnoManualCreate(**_manual()).sobreturno is False
    assert TurnoManualCreate(**_manual(sobreturno=True)).sobreturno is True


@pytest.mark.parametrize(
    "cambios",
    [
        {"estado": "confirmado"},
        {"fin": INICIO},
        {"origen": "online"},
        {"inicio": "2030-03-04T10:00:00"},  # naive
        {"paciente_telefono": "11 5555-0000"},
        {"paciente_nombre": "   "},
    ],
)
def test_manual_rechaza_extra_naive_y_telefono_invalido(cambios):
    with pytest.raises(ValidationError):
        TurnoManualCreate(**_manual(**cambios))


def test_reprogramar_solo_inicio_y_sobreturno():
    datos = TurnoReprogramar(inicio=INICIO)
    assert datos.sobreturno is False and datos.inicio.utcoffset() is not None
    assert TurnoReprogramar(inicio=INICIO, sobreturno=True).sobreturno is True


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"inicio": INICIO, "profesional_id": str(uuid.uuid4())},
        {"inicio": INICIO, "estado": "reservado"},
        {"inicio": "2030-03-04T10:00:00"},
        {},
    ],
)
def test_reprogramar_rechaza_extra_naive_o_faltante(cuerpo):
    with pytest.raises(ValidationError):
        TurnoReprogramar(**cuerpo)


def _gestionado(**extra) -> dict:
    ini = datetime(2030, 3, 4, 13, 0, tzinfo=timezone.utc)
    return {
        "id": uuid.uuid4(),
        "profesional_id": uuid.uuid4(),
        "paciente_id": uuid.uuid4(),
        "tratamiento_id": None,
        "inicio": ini,
        "fin": ini,
        "estado": "reservado",
        "origen": "secretaria",
        "sobreturno": False,
        **extra,
    }


def test_gestionado_no_tiene_token_publico_y_lo_rechaza():
    assert "token_publico" not in TurnoGestionadoOut.model_fields
    with pytest.raises(ValidationError):
        TurnoGestionadoOut(**_gestionado(token_publico="x"))


@pytest.mark.parametrize(
    "estado", ["reservado", "confirmado", "cancelado", "atendido", "ausente"]
)
def test_gestionado_acepta_los_5_estados(estado):
    assert TurnoGestionadoOut(**_gestionado(estado=estado)).estado == estado


def test_gestionado_rechaza_estado_desconocido():
    with pytest.raises(ValidationError):
        TurnoGestionadoOut(**_gestionado(estado="otro"))


def test_turno_create_sigue_rechazando_sobreturno():
    with pytest.raises(ValidationError):
        TurnoCreate(**_manual(sobreturno=True))


def _creado(**extra) -> dict:
    return {**_gestionado(), "token_publico": "tok", "estado": "reservado", **extra}


def test_manual_creado_exige_origen_secretaria_y_conserva_token():
    ok = TurnoManualCreado(**_creado())
    assert ok.token_publico == "tok" and ok.paciente_id is not None
    with pytest.raises(ValidationError):
        TurnoManualCreado(**_creado(origen="online"))
    with pytest.raises(ValidationError):
        TurnoManualCreado(**_creado(estado="confirmado"))
