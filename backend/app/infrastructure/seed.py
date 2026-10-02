"""Seed mínimo idempotente (C-02).

CLI explícito (`python -m app.infrastructure.seed`), NUNCA auto-run en
import/startup. Idempotencia por get-or-create sobre claves naturales.
`CANCEL_MIN_HOURS` se lee de settings (SU-01, nunca hardcode) y solo se
logea/retorna: el seed no crea tabla de parámetros (YAGNI). Datos 100 %
sintéticos (dominio `example.test`, matrícula de ejemplo).
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.core.settings import get_settings
from app.infrastructure.models import Profesional, Tratamiento, User, UserRole

logger = logging.getLogger(__name__)

SEED_SECRETARIA_EMAIL = "secretaria@example.test"
SEED_SECRETARIA_PASSWORD = "Seed-Secretaria-123"
SEED_PROFESIONAL_MATRICULA = "MAT-EJ-001"
SEED_TRATAMIENTOS: tuple[tuple[str, int], ...] = (
    ("Limpieza", 30),
    ("Consulta", 20),
    ("Tratamiento de conducto", 60),
)


def run_seed(session: Session) -> dict[str, int]:
    cancel_min_hours = get_settings().CANCEL_MIN_HOURS
    if cancel_min_hours < 0:
        raise ValueError(f"CANCEL_MIN_HOURS inválido: {cancel_min_hours}")
    logger.info("seed con CANCEL_MIN_HOURS=%s", cancel_min_hours)

    existente = session.scalar(select(User).where(User.email == SEED_SECRETARIA_EMAIL))
    if existente is None:
        session.add(
            User(
                email=SEED_SECRETARIA_EMAIL,
                password_hash=hash_password(SEED_SECRETARIA_PASSWORD),
                rol=UserRole.SECRETARIA,
            )
        )

    if (
        session.scalar(
            select(Profesional).where(
                Profesional.matricula == SEED_PROFESIONAL_MATRICULA
            )
        )
        is None
    ):
        session.add(
            Profesional(
                nombre="Dra. Ejemplo",
                matricula=SEED_PROFESIONAL_MATRICULA,
                especialidad="Odontología general",
                slot_default_min=30,
            )
        )

    for nombre, duracion_min in SEED_TRATAMIENTOS:
        if session.scalar(select(Tratamiento).where(Tratamiento.nombre == nombre)) is None:
            session.add(Tratamiento(nombre=nombre, duracion_min=duracion_min))

    session.commit()
    return {
        "users": session.query(User).count(),
        "profesionales": session.query(Profesional).count(),
        "tratamientos": session.query(Tratamiento).count(),
        "cancel_min_hours": cancel_min_hours,
    }


def main() -> None:
    session = SessionLocal()
    try:
        resultado = run_seed(session)
    finally:
        session.close()
    print(
        f"seed ok: users={resultado['users']} "
        f"profesionales={resultado['profesionales']} "
        f"tratamientos={resultado['tratamientos']} "
        f"CANCEL_MIN_HOURS={resultado['cancel_min_hours']}"
    )


if __name__ == "__main__":
    main()
