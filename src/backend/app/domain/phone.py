"""Teléfono E.164 (C-02, DD-03).

Única fuente de la regex: la usan el validador Pydantic (`domain/schemas.py`)
y el CHECK de Postgres (`infrastructure/models.py`). Defensa en profundidad.
"""

from typing import Annotated

from pydantic import Field

E164_PATTERN = r"^\+[1-9][0-9]{7,14}$"

TelefonoE164 = Annotated[str, Field(pattern=E164_PATTERN, min_length=8, max_length=16)]
