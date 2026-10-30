"""C-06 3.2: schemas de bloqueos y agenda (D5, D6). Strict, sin campos fantasma."""

import uuid

import pytest
from pydantic import ValidationError

from app.domain.schemas import (
    AgendaBloqueoOut,
    AgendaOut,
    AgendaTurnoOut,
    BloqueoCreate,
    BloqueoOut,
)

DESDE = "2030-03-04T09:00:00-03:00"
HASTA = "2030-03-04T13:00:00-03:00"


def _create(**extra) -> dict:
    return {
        "profesional_id": str(uuid.uuid4()),
        "desde": DESDE,
        "hasta": HASTA,
        "motivo": "Capacitacion",
        **extra,
    }


def test_bloqueo_create_valido_recorta_espacios_del_motivo():
    b = BloqueoCreate(**_create(motivo="  Vacaciones  "))
    assert b.motivo == "Vacaciones" and b.desde < b.hasta


def test_bloqueo_create_acepta_motivo_de_200_caracteres():
    assert len(BloqueoCreate(**_create(motivo="x" * 200)).motivo) == 200


@pytest.mark.parametrize(
    "cambios",
    [
        {"hasta": DESDE},  # hasta == desde
        {"hasta": "2030-03-04T08:00:00-03:00"},  # hasta < desde
        {"desde": "2030-03-04T09:00:00"},  # naive
        {"hasta": "2030-03-04T13:00:00"},  # naive
        {"motivo": ""},
        {"motivo": "   "},
        {"motivo": "x" * 201},
        {"estado": "x"},  # campo extra
        {"is_active": False},  # campo extra
    ],
)
def test_bloqueo_create_rechaza_entradas_invalidas(cambios):
    with pytest.raises(ValidationError):
        BloqueoCreate(**_create(**cambios))


def test_bloqueo_create_requiere_todos_los_campos():
    for campo in ("profesional_id", "desde", "hasta", "motivo"):
        datos = _create()
        del datos[campo]
        with pytest.raises(ValidationError):
            BloqueoCreate(**datos)


def _bloqueo_out(**extra) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "profesional_id": str(uuid.uuid4()),
        "desde": DESDE,
        "hasta": HASTA,
        "motivo": "Capacitacion",
        **extra,
    }


def test_bloqueo_out_exacto_y_rechaza_extra():
    assert set(BloqueoOut(**_bloqueo_out()).model_dump()) == {
        "id", "profesional_id", "desde", "hasta", "motivo",
    }
    with pytest.raises(ValidationError):
        BloqueoOut(**_bloqueo_out(deleted_at=None))


def _turno_out(**extra) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "inicio": DESDE,
        "fin": "2030-03-04T09:30:00-03:00",
        "estado": "reservado",
        "origen": "online",
        "sobreturno": False,
        "paciente": {"id": str(uuid.uuid4()), "nombre": "Paciente S", "telefono": "+5491100000000"},
        "tratamiento": {"id": 1, "nombre": "Limpieza"},
        **extra,
    }


@pytest.mark.parametrize(
    "estado", ["reservado", "confirmado", "cancelado", "atendido", "ausente"]
)
def test_agenda_turno_acepta_los_cinco_estados(estado):
    assert AgendaTurnoOut(**_turno_out(estado=estado)).estado == estado


def test_agenda_turno_tratamiento_nulo_y_sin_token_publico():
    t = AgendaTurnoOut(**_turno_out(tratamiento=None))
    assert t.tratamiento is None
    assert "token_publico" not in AgendaTurnoOut.model_fields
    with pytest.raises(ValidationError):
        AgendaTurnoOut(**_turno_out(token_publico="abc"))


@pytest.mark.parametrize(
    "cambios",
    [
        {"estado": "pendiente"},
        {"origen": "whatsapp"},
        {"inicio": "2030-03-04T09:00:00"},
        {"paciente": {"id": str(uuid.uuid4()), "nombre": "P", "telefono": "+5491100000000", "dni": "1"}},
        {"extra": 1},
    ],
)
def test_agenda_turno_rechaza_invalidos(cambios):
    with pytest.raises(ValidationError):
        AgendaTurnoOut(**_turno_out(**cambios))


def test_agenda_bloqueo_out_y_agenda_out_compuesta():
    b = {"id": str(uuid.uuid4()), "desde": DESDE, "hasta": HASTA, "motivo": "Feriado"}
    assert set(AgendaBloqueoOut(**b).model_dump()) == {"id", "desde", "hasta", "motivo"}
    agenda = AgendaOut(
        profesional={"id": str(uuid.uuid4()), "nombre": "Dra. S"},
        vista="semana",
        desde="2030-03-04",
        hasta="2030-03-10",
        turnos=[_turno_out()],
        bloqueos=[b],
    )
    assert agenda.vista == "semana" and len(agenda.turnos) == 1 and len(agenda.bloqueos) == 1


def test_agenda_out_rechaza_vista_invalida_y_extra():
    base = {
        "profesional": {"id": str(uuid.uuid4()), "nombre": "Dra. S"},
        "vista": "dia",
        "desde": "2030-03-04",
        "hasta": "2030-03-04",
        "turnos": [],
        "bloqueos": [],
    }
    AgendaOut(**base)
    with pytest.raises(ValidationError):
        AgendaOut(**{**base, "vista": "mes"})
    with pytest.raises(ValidationError):
        AgendaOut(**{**base, "x": 1})
