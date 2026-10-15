import pytest
from datetime import timedelta
from app.core.security import create_access_token, create_refresh_token, decode_token


def test_jwt_access_and_refresh_tokens():
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    email = "secretaria@clinica.com"
    rol = "secretaria"

    access_token = create_access_token(subject=user_id, email=email, rol=rol)
    refresh_token = create_refresh_token(subject=user_id)

    assert isinstance(access_token, str)
    assert isinstance(refresh_token, str)

    # Decode access token
    access_payload = decode_token(access_token, token_type="access")
    assert access_payload["sub"] == user_id
    assert access_payload["email"] == email
    assert access_payload["rol"] == rol
    assert access_payload["type"] == "access"
    assert "jti" in access_payload

    # Decode refresh token
    refresh_payload = decode_token(refresh_token, token_type="refresh")
    assert refresh_payload["sub"] == user_id
    assert refresh_payload["type"] == "refresh"
    assert "jti" in refresh_payload
