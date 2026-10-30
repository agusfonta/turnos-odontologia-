"""Repositorios de agenda (C-04): queries de intervalo, UNA por tabla (sin N+1).

Devuelven solo lo que necesita el dominio (`(inicio, fin)` / `Franja`), nunca
entidades completas (no filtran `token_publico` ni datos de pacientes).
Intersección con el rango consultado `[desde, hasta)`: `inicio < hasta AND fin > desde`
(los que solo tocan el borde, semiabierto, no cuentan). Todo `def`.
"""

import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.disponibilidad import Franja, Ocupado
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import Bloqueo, HorarioProfesional, Turno, TurnoOrigen
from app.infrastructure.repositories import BaseRepository

EXCLUSION_SIN_SOLAPE = "ex_turnos_sin_solape"


class TurnoRepository(BaseRepository[Turno]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Turno)

    def insertar_si_no_solapa(
        self,
        *,
        profesional_id: uuid.UUID,
        paciente_id: uuid.UUID,
        tratamiento_id: int | None,
        inicio: datetime,
        fin: datetime,
        origen: TurnoOrigen,
        token_publico: str,
        created_by: uuid.UUID | None,
        sobreturno: bool = False,
    ) -> uuid.UUID | None:
        """Alta `reservado`; `None` si la exclusion constraint la rechaza por solape.

        `ON CONFLICT ON CONSTRAINT ex_turnos_sin_solape DO NOTHING`: la constraint de la
        DB sigue decidiendo (es el arbitro), pero via insercion especulativa, que espera a
        la transaccion rival y NO deadlockea. Un INSERT comun si puede: dos altas
        solapadas concurrentes insertan su tupla y se esperan mutuamente al verificar la
        constraint (40P01). Cualquier otra violacion (CHECK, FK, unique) se propaga.

        `sobreturno=True` deja la fila fuera del WHERE de la constraint (nunca conflictua);
        el default `False` conserva el comportamiento de la reserva.
        """
        stmt = (
            pg_insert(Turno)
            .values(
                profesional_id=profesional_id,
                paciente_id=paciente_id,
                tratamiento_id=tratamiento_id,
                inicio=inicio,
                fin=fin,
                estado=EstadoTurno.RESERVADO,
                origen=origen,
                token_publico=token_publico,
                created_by=created_by,
                sobreturno=sobreturno,
            )
            .on_conflict_do_nothing(constraint=EXCLUSION_SIN_SOLAPE)
            .returning(Turno.id)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def ocupados_en_rango(
        self,
        profesional_id: uuid.UUID,
        desde: datetime,
        hasta: datetime,
        *,
        excluir_turno_id: uuid.UUID | None = None,
    ) -> list[Ocupado]:
        """Turnos no cancelados del profesional que intersectan `[desde, hasta)`.

        `excluir_turno_id` descarta un turno (el que se esta reprogramando).
        """
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
        if excluir_turno_id is not None:
            stmt = stmt.where(Turno.id != excluir_turno_id)
        return [(inicio, fin) for inicio, fin in self._session.execute(stmt)]

    def bloquear_agenda(self, profesional_id: uuid.UUID) -> None:
        """Advisory lock transaccional por profesional (C-05 D4).

        Serializa las escrituras de secretaria que ocupan la agenda del profesional;
        se libera solo al commit/rollback. Una colision de `hashtext` solo serializa de mas.
        """
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:p))"), {"p": str(profesional_id)}
        )

    def profesional_de(self, turno_id: uuid.UUID) -> uuid.UUID | None:
        """`profesional_id` del turno sin lockear la fila (`None` si no existe)."""
        return self._session.execute(
            select(Turno.profesional_id).where(Turno.id == turno_id)
        ).scalar_one_or_none()

    def obtener_para_actualizar(self, turno_id: uuid.UUID) -> Turno | None:
        """`SELECT ... FOR UPDATE` del turno (relee el estado vigente, sin cache de sesion)."""
        return self._session.execute(
            select(Turno)
            .where(Turno.id == turno_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()


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
