"""App FastAPI (monolito modular). Prefijo global /api para no colisionar con la SPA."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.agenda import router as agenda_router
from app.api.auth import router as auth_router
from app.api.bloqueos import router as bloqueos_router
from app.api.disponibilidad import router as disponibilidad_router
from app.api.profesionales import router as profesionales_router
from app.api.turnos import router as turnos_router
from app.api.tratamientos import router as tratamientos_router
from app.core.exceptions import register_exception_handlers
from app.core.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="Turnos Odontología API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(profesionales_router, prefix="/api")
    app.include_router(tratamientos_router, prefix="/api")
    app.include_router(disponibilidad_router, prefix="/api")
    app.include_router(turnos_router, prefix="/api")
    app.include_router(bloqueos_router, prefix="/api")
    app.include_router(agenda_router, prefix="/api")
    return app


app = create_app()
