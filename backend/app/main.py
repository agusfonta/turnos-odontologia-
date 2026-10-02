"""App FastAPI (monolito modular). Prefijo global /api para no colisionar con la SPA."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
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
    return app


app = create_app()
