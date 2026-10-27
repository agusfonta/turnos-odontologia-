"""Repositorios de agenda (C-04): queries de intervalo, UNA por tabla (sin N+1).

Devuelven solo lo que necesita el dominio (`(inicio, fin)` / `Franja`), nunca
entidades completas (no filtran `token_publico` ni datos de pacientes).
Intersección con el rango consultado `[desde, hasta)`: `inicio < hasta AND fin > desde`
(los que solo tocan el borde, semiabierto, no cuentan). Todo `def`.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.disponibilidad import Franja, Ocupado
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import Bloqueo, HorarioProfesional, Turno
from app.infrastructure.repositories import BaseRepository


class TurnoRepository(BaseRepository[Turno]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Turno)

    def ocupados_en_rango(
        self, profesional_id: uuid.UUID, desde: datetime, hasta: datetime
    ) -> list[Ocupado]:
        """Turnos no cancelados del profesional que intersectan `[desde, hasta)`."""
        stmt = (
            select(Turno.inicio, Turno.fin)
            .where(
                Turno.profesional_id == profesional_id,
                Turno.estado != EstadoTurno.CANCELADO,
                Turno.inicio < hasta,
                Turno.fin > desde,
            )
            .order_by(Turno.inicio)
        )
        return [(inicio, fin) for inicio, fin in self._session.execute(stmt)]


class BloqueoRepository(BaseRepository[Bloqueo]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Bloqueo)

    def ocupados_en_rango(
        self, profesional_id: uuid.UUID, desde: datetime, hasta: datetime
    ) -> list[Ocupado]:
        """Bloqueos activos del profesional que intersectan `[desde, hasta)`."""
        stmt = (
            select(Bloqueo.desde, Bloqueo.hasta)
            .where(
                Bloqueo.profesional_id == profesional_id,
                Bloqueo.is_active.is_(True),
                Bloqueo.desde < hasta,
                Bloqueo.hasta > desde,
            )
            .order_by(Bloqueo.desde)
        )
        return [(ini, fin) for ini, fin in self._session.execute(stmt)]


class HorarioRepository(BaseRepository[HorarioProfesional]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, HorarioProfesional)

    def activas_por_profesional(self, profesional_id: uuid.UUID) -> list[Franja]:
        """Franjas activas del profesional (solo dia/hora_inicio/hora_fin)."""
        stmt = (
            select(
                HorarioProfesional.dia_semana,
                HorarioProfesional.hora_inicio,
                HorarioProfesional.hora_fin,
            )
            .where(
                HorarioProfesional.profesional_id == profesional_id,
                HorarioProfesional.is_active.is_(True),
            )
            .order_by(
                HorarioProfesional.dia_semana, HorarioProfesional.hora_inicio
            )
        )
        return [Franja(dia, ini, fin) for dia, ini, fin in self._session.execute(stmt)]
