"""Schemas Pydantic estrictos de C-02 (validación en capa app).

Espejan las columnas sin campos fantasma. Sin `...` defaults (regla fastapi).
"""

import uuid
from typing import Literal

from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.phone import TelefonoE164

RolStaff = Literal["secretaria", "odontologo"]


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=5, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    rol: RolStaff

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()


class ProfesionalCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: str = Field(min_length=1, max_length=200)
    matricula: str = Field(min_length=1, max_length=50)
    especialidad: str | None = Field(default=None, max_length=120)
    slot_default_min: int = Field(default=30, gt=0)


class PacienteCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: str = Field(min_length=1, max_length=200)
    telefono: TelefonoE164
    dni: str | None = Field(default=None, max_length=16)


class TratamientoCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: str = Field(min_length=1, max_length=120)
    duracion_min: int = Field(gt=0)


# --- Respuestas publicas de agenda (C-04). Strict: sin campos fantasma. ---


class ProfesionalPublico(BaseModel):
    """Sin matricula ni auditoria (dato interno)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    nombre: str
    especialidad: str | None


class TratamientoPublico(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    nombre: str
    duracion_min: int


class HuecoPublico(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    inicio: AwareDatetime
    fin: AwareDatetime


# --- Reserva de turnos (C-04) ---


class TurnoCreate(BaseModel):
    """Entrada de POST /api/turnos. El cliente NO define `fin`, `estado`,
    `origen` ni `sobreturno` (extra=forbid => 422)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    profesional_id: uuid.UUID
    inicio: AwareDatetime
    tratamiento_id: int | None = None
    paciente_nombre: str = Field(min_length=1, max_length=200)
    paciente_telefono: TelefonoE164


class TurnoCreado(BaseModel):
    """Respuesta 201. `token_publico` solo se devuelve en la creacion."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    profesional_id: uuid.UUID
    tratamiento_id: int | None
    inicio: AwareDatetime
    fin: AwareDatetime
    estado: Literal["reservado"]
    origen: Literal["online", "secretaria"]
    token_publico: str


# --- Gestion de secretaria (C-05, D9) ---

EstadoTurnoLiteral = Literal["reservado", "confirmado", "cancelado", "atendido", "ausente"]


class TurnoManualCreate(TurnoCreate):
    """Entrada de POST /api/turnos/manual: los campos de `TurnoCreate` + `sobreturno`."""

    sobreturno: bool = False


class TurnoReprogramar(BaseModel):
    """Entrada de PATCH /api/turnos/{id}: solo el nuevo `inicio` (y la marca de sobreturno)."""

    model_config = ConfigDict(extra="forbid")

    inicio: AwareDatetime
    sobreturno: bool = False


class TurnoManualCreado(TurnoCreado):
    """201 del alta manual; conserva `token_publico` (es una creacion)."""

    origen: Literal["secretaria"]  # type: ignore[assignment]
    paciente_id: uuid.UUID
    sobreturno: bool


class TurnoGestionadoOut(BaseModel):
    """Respuesta de reprogramar/cancelar. Sin `token_publico`."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    profesional_id: uuid.UUID
    paciente_id: uuid.UUID
    tratamiento_id: int | None
    inicio: AwareDatetime
    fin: AwareDatetime
    estado: EstadoTurnoLiteral
    origen: Literal["online", "secretaria"]
    sobreturno: bool


# --- Bloqueos y agenda (C-06, D5/D6) ---


class BloqueoCreate(BaseModel):
    """Entrada de POST /api/bloqueos. `desde >= ahora` lo valida el caso de uso (reloj inyectado)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    profesional_id: uuid.UUID
    desde: AwareDatetime
    hasta: AwareDatetime
    motivo: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _hasta_posterior_a_desde(self) -> "BloqueoCreate":
        if self.hasta <= self.desde:
            raise ValueError("hasta debe ser posterior a desde")
        return self


class BloqueoOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    profesional_id: uuid.UUID
    desde: AwareDatetime
    hasta: AwareDatetime
    motivo: str


class AgendaProfesionalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    nombre: str


class AgendaPacienteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    nombre: str
    telefono: str


class AgendaTratamientoOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    nombre: str


class AgendaTurnoOut(BaseModel):
    """Turno de la agenda interna. Sin `token_publico`; incluye `cancelado`."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    inicio: AwareDatetime
    fin: AwareDatetime
    estado: EstadoTurnoLiteral
    origen: Literal["online", "secretaria"]
    sobreturno: bool
    paciente: AgendaPacienteOut
    tratamiento: AgendaTratamientoOut | None


class AgendaBloqueoOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    desde: AwareDatetime
    hasta: AwareDatetime
    motivo: str


class AgendaOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profesional: AgendaProfesionalOut
    vista: Literal["dia", "semana"]
    desde: date
    hasta: date
    turnos: list[AgendaTurnoOut]
    bloqueos: list[AgendaBloqueoOut]
