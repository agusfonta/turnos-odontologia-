"""Anticipacion minima por actor (C-05 D7, DD-05). Dominio puro, reloj inyectado."""

from datetime import datetime, timedelta

from app.core.exceptions import AnticipacionInsuficienteError
from app.infrastructure.models import AuditoriaActor


def verificar_anticipacion(
    inicio_actual: datetime,
    ahora: datetime,
    *,
    actor_tipo: AuditoriaActor,
    min_horas: int,
) -> bool:
    """Valida el horario que se libera. Devuelve `True` si hubo exencion.

    Paciente: exige `inicio_actual - ahora >= min_horas` (borde inclusivo).
    Secretaria: solo exige que el turno no haya empezado; si cae dentro de la
    ventana de paciente devuelve `True` (se audita como `exento_anticipacion`).
    """
    ventana = timedelta(hours=min_horas)
    dentro_de_ventana = inicio_actual - ahora < ventana
    if actor_tipo is AuditoriaActor.SECRETARIA:
        if inicio_actual <= ahora:
            raise AnticipacionInsuficienteError(min_horas)
        return dentro_de_ventana
    if dentro_de_ventana:
        raise AnticipacionInsuficienteError(min_horas)
    return False
