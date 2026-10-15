"""Base de dominio: AuditMixin (soft delete + timestamps).

`is_active=false` + `deleted_at` es el borrado lógico; los listados excluyen
inactivos por defecto (ver `infrastructure/repositories.py` en T3).
Todo `def` sincrónico (regla dura async).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, func, text
from sqlalchemy.orm import Mapped, mapped_column


class AuditMixin:
    """Columnas de auditoría para todas las entidades (C-02)."""

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    def soft_delete(self) -> None:
        """Marca la fila como inactiva (borrado lógico)."""
        self.is_active = False
        self.deleted_at = datetime.now(timezone.utc)
