"""C-05 2.2: anticipacion por actor (D7, DD-05). Dominio puro."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import AnticipacionInsuficienteError
from app.domain.anticipacion import verificar_anticipacion
from app.infrastructure.models import AuditoriaActor

AHORA = datetime(2030, 3, 4, 12, 0, tzinfo=timezone.utc)


def _en(horas: float) -> datetime:
    return AHORA + timedelta(hours=horas)


def test_paciente_dentro_de_la_ventana_rechaza():
    with pytest.raises(AnticipacionInsuficienteError) as exc:
        verificar_anticipacion(_en(23), AHORA, actor_tipo=AuditoriaActor.PACIENTE, min_horas=24)
    assert exc.value.min_horas == 24


def test_paciente_con_exactamente_min_horas_acepta_borde_inclusivo():
    assert (
        verificar_anticipacion(_en(24), AHORA, actor_tipo=AuditoriaActor.PACIENTE, min_horas=24)
        is False
    )


def test_paciente_con_min_horas_configurable():
    assert (
        verificar_anticipacion(_en(4), AHORA, actor_tipo=AuditoriaActor.PACIENTE, min_horas=3)
        is False
    )
    with pytest.raises(AnticipacionInsuficienteError):
        verificar_anticipacion(_en(2), AHORA, actor_tipo=AuditoriaActor.PACIENTE, min_horas=3)


def test_secretaria_dentro_de_la_ventana_acepta_y_marca_exento():
    assert (
        verificar_anticipacion(_en(2), AHORA, actor_tipo=AuditoriaActor.SECRETARIA, min_horas=24)
        is True
    )


def test_secretaria_fuera_de_la_ventana_no_es_exenta():
    assert (
        verificar_anticipacion(_en(48), AHORA, actor_tipo=AuditoriaActor.SECRETARIA, min_horas=24)
        is False
    )


@pytest.mark.parametrize("delta_h", [0, -1])
def test_secretaria_con_turno_ya_iniciado_rechaza(delta_h):
    with pytest.raises(AnticipacionInsuficienteError):
        verificar_anticipacion(
            _en(delta_h), AHORA, actor_tipo=AuditoriaActor.SECRETARIA, min_horas=24
        )
