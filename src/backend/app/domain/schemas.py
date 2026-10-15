"""Schemas Pydantic estrictos de C-02 (validación en capa app).

Espejan las columnas sin campos fantasma. Sin `...` defaults (regla fastapi).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
