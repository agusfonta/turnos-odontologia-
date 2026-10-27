"""GET /api/tratamientos: listado publico de tratamientos activos (C-04, sin auth)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domain.schemas import TratamientoPublico
from app.infrastructure.models import Tratamiento
from app.infrastructure.repositories import BaseRepository

router = APIRouter(prefix="/tratamientos", tags=["tratamientos"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[TratamientoPublico])
def listar_tratamientos(db: DbDep) -> list[Tratamiento]:
    return BaseRepository(db, Tratamiento).list(order_by=Tratamiento.nombre)
