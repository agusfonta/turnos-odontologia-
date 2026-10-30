"""Cola de recordatorios en Redis (C-04, design Decision 9).

Contrato para el worker de C-08:
  * Estructura: sorted set `jobs:recordatorios`.
  * Miembro: `str(turno_id)` (UUID). Idempotente: re-encolar no duplica.
  * Score: epoch (segundos, float, UTC) de `inicio - 24 h` (instante objetivo).
  * Reintento: 3 intentos, backoff 50/100 ms; si fallan, `logger.warning` con el
    `turno_id` y se sigue (la reserva NUNCA depende de Redis).
Se llama SIEMPRE despues del commit. Nunca se envia WhatsApp aca.
"""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import redis

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

RECORDATORIOS_KEY = "jobs:recordatorios"
ANTICIPACION_RECORDATORIO = timedelta(hours=24)
BACKOFF_SEGUNDOS = (0.05, 0.1)  # espera tras el intento 1 y el 2 (3 intentos en total)


class RecordatorioQueue:
    def __init__(self, client: Any, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._client = client
        self._sleep = sleep

    def _con_reintento(
        self, operacion: Callable[[], object], accion: str, turno_id: uuid.UUID
    ) -> bool:
        """3 intentos con backoff; `False` (sin lanzar) + warning con `turno_id` si fallan."""
        intentos = len(BACKOFF_SEGUNDOS) + 1
        for intento in range(1, intentos + 1):
            try:
                operacion()
                return True
            except redis.RedisError as exc:
                if intento < intentos:
                    self._sleep(BACKOFF_SEGUNDOS[intento - 1])
                else:
                    logger.warning(
                        "no se pudo %s recordatorio turno_id=%s tras %s intentos: %s",
                        accion,
                        turno_id,
                        intentos,
                        exc.__class__.__name__,
                    )
        return False

    def encolar(self, turno_id: uuid.UUID, inicio: datetime) -> bool:
        """ZADD idempotente (sobre un miembro existente actualiza el score).

        Devuelve False (sin lanzar) si Redis falla 3 veces.
        """
        score = (inicio - ANTICIPACION_RECORDATORIO).timestamp()
        return self._con_reintento(
            lambda: self._client.zadd(RECORDATORIOS_KEY, {str(turno_id): score}),
            "encolar",
            turno_id,
        )

    def cancelar(self, turno_id: uuid.UUID) -> bool:
        """ZREM del job (C-05 D10); un turno sin job es exito. Nunca lanza."""
        return self._con_reintento(
            lambda: self._client.zrem(RECORDATORIOS_KEY, str(turno_id)),
            "cancelar",
            turno_id,
        )


def get_recordatorio_queue() -> RecordatorioQueue:
    """Dependencia FastAPI; los tests la sobreescriben con fakeredis / un fake que falla."""
    client = redis.Redis.from_url(
        get_settings().REDIS_URL, socket_timeout=0.5, socket_connect_timeout=0.5
    )
    return RecordatorioQueue(client)
