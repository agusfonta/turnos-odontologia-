import pytest
from unittest.mock import patch
import fakeredis
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.db import get_db
from app.infrastructure.models import User, UserRole
from app.core.security import hash_password

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_redis():
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    with patch("app.core.security.get_redis_client", return_value=fake_redis):
        yield fake_redis


@pytest.fixture(autouse=True)
def test_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    session = Session(engine)

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    yield session
    session.close()
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def seed_users(test_db_session: Session):
    sec = User(
        email="sec@clinica.com",
        password_hash=hash_password("Password123!"),
        rol=UserRole.SECRETARIA,
    )
    odonto = User(
        email="odonto@clinica.com",
        password_hash=hash_password("Password123!"),
        rol=UserRole.ODONTOLOGO,
    )
    test_db_session.add_all([sec, odonto])
    test_db_session.commit()
    return sec, odonto


def test_login_success(seed_users):
    response = client.post(
        "/api/auth/login",
        json={"email": "sec@clinica.com", "password": "Password123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "sec@clinica.com"
    assert data["user"]["rol"] == "secretaria"
    assert "refresh_token" in response.cookies


def test_login_invalid_credentials(seed_users):
    response = client.post(
        "/api/auth/login",
        json={"email": "sec@clinica.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401


def test_login_rate_limit(seed_users):
    for _ in range(3):
        resp = client.post(
            "/api/auth/login",
            json={"email": "sec@clinica.com", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    resp_blocked = client.post(
        "/api/auth/login",
        json={"email": "sec@clinica.com", "password": "WrongPassword!"},
    )
    assert resp_blocked.status_code == 429


def test_me_and_rbac(seed_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "odonto@clinica.com", "password": "Password123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "odonto@clinica.com"
    assert me_resp.json()["rol"] == "odontologo"


def test_refresh_token(seed_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "sec@clinica.com", "password": "Password123!"},
    )
    assert login_resp.status_code == 200

    refresh_resp = client.post("/api/auth/refresh")
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()


def test_logout(seed_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "sec@clinica.com", "password": "Password123!"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    logout_resp = client.post("/api/auth/logout", headers=headers)
    assert logout_resp.status_code == 200

    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 401


def test_rbac_forbidden(seed_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "odonto@clinica.com", "password": "Password123!"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/auth/secretaria-only", headers=headers)
    assert resp.status_code == 403

    resp_ok = client.get("/api/auth/odontologo-only", headers=headers)
    assert resp_ok.status_code == 200
