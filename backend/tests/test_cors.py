"""Bugfix CORS: el frontend (:5173) debe poder leer la API (:8000) desde el navegador."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_responde_acao_al_origen_del_frontend() -> None:
    client = TestClient(create_app())
    res = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") in (
        "http://localhost:5173",
        "*",
    )


def test_preflight_options_habilita_get() -> None:
    client = TestClient(create_app())
    res = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.status_code == 200
    assert "GET" in res.headers.get("access-control-allow-methods", "")
