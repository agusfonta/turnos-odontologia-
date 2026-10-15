"""Unit of Work sincrónica (C-02): context manager commit/rollback.

Usa `SessionLocal` por defecto (misma sesión que `get_db`); los tests
inyectan su propia factoría apuntando a la DB de test. Todo `def`.
"""

from collections.abc import Callable
from types import TracebackType

from sqlalchemy.orm import Session

from app.core.db import SessionLocal


class UnitOfWork:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> Session:
        self.session = self._factory()
        return self.session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self.session is not None
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None
