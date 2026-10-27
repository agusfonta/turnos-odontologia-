"""GET /api/profesionales: listado publico de profesionales activos (C-04, sin auth)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domain.schemas import ProfesionalPublico
from app.infrastructure.models import Profesional
from app.infrastructure.repositories import BaseRepository

router = APIRouter(prefix="/profesionales", tags=["profesionales"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[ProfesionalPublico])
def listar_profesionales(db: DbDep) -> list[Profesional]:
    return BaseRepository(db, Profesional).list(order_by=Profesional.nombre)
