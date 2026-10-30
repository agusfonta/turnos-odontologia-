"""Repositorio genérico sincrónico (C-02).

`list` excluye inactivos por defecto y pagina con orden determinista por PK.
Todo `def` (regla dura async).
"""

from typing import Generic, TypeVar, cast

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domain.base import AuditMixin
from app.infrastructure.models import Paciente

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, session: Session, model: type[T]) -> None:
        self._session = session
        self._model = model

    def add(self, entity: T) -> T:
        self._session.add(entity)
        return entity

    def get(self, entity_id: object) -> T | None:
        return self._session.get(self._model, entity_id)  # type: ignore[arg-type]

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        include_inactive: bool = False,
        order_by: ColumnElement | None = None,
    ) -> list[T]:
        stmt = select(self._model)
        is_active_col = getattr(self._model, "is_active", None)
        if not include_inactive and is_active_col is not None:
            stmt = stmt.where(is_active_col.is_(True))
        pk = next(iter(self._model.__table__.primary_key.columns.values()))
        # `order_by` primero; la PK desempata para mantener orden determinista.
        orden = [pk] if order_by is None else [order_by, pk]
        stmt = stmt.order_by(*orden).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all())

    def soft_delete(self, entity: T) -> T:
        cast(AuditMixin, entity).soft_delete()
        return entity


class PacienteRepository(BaseRepository[Paciente]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Paciente)

    def buscar_por_telefono(self, telefono: str) -> Paciente | None:
        """Paciente activo mas antiguo con ese telefono E.164 (DD-06; indice no unico)."""
        stmt = (
            select(Paciente)
            .where(Paciente.telefono == telefono, Paciente.is_active.is_(True))
            .order_by(Paciente.created_at, Paciente.id)
            .limit(1)
        )
        return self._session.scalars(stmt).first()
