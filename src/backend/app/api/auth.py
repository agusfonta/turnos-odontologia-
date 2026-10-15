"""Endpoints de autenticación y RBAC (`/api/auth/*`, C-03)."""

from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_odontologo, require_secretaria
from app.core.db import get_db
from app.core.security import (
    blacklist_token,
    check_login_rate_limit,
    clear_login_rate_limit,
    create_access_token,
    create_refresh_token,
    decode_token,
    record_failed_login,
    verify_password,
)
from app.infrastructure.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: str
    email: str
    rol: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    ip = request.client.host if request.client and request.client.host else "127.0.0.1"
    email = login_data.email

    check_login_rate_limit(ip, email)

    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active or not verify_password(login_data.password, user.password_hash):
        record_failed_login(ip, email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    clear_login_rate_limit(ip, email)

    access_token = create_access_token(str(user.id), user.email, user.rol.value)
    refresh_token = create_refresh_token(str(user.id))

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )

    return TokenResponse(
        access_token=access_token,
        user=UserResponse(id=str(user.id), email=user.email, rol=user.rol.value),
    )


@router.post("/refresh")
def refresh_token_endpoint(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    payload = decode_token(refresh_token, token_type="refresh")
    user_id_str = payload.get("sub")
    old_jti = payload.get("jti")

    if old_jti:
        blacklist_token(old_jti, expires_in_seconds=7 * 24 * 3600)

    try:
        user_id = uuid.UUID(user_id_str)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user id format",
        )

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    new_access_token = create_access_token(str(user.id), user.email, user.rol.value)
    new_refresh_token = create_refresh_token(str(user.id))

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )

    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = decode_token(token, token_type="access")
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti:
                ttl = int(exp - datetime.now(timezone.utc).timestamp()) if exp else 86400
                blacklist_token(jti, max(ttl, 60))
        except Exception:
            pass

    response.delete_cookie("refresh_token")
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        rol=current_user.rol.value,
    )


@router.get("/secretaria-only")
def secretaria_only(current_user: User = Depends(require_secretaria)):
    return {"message": "Access granted for secretaria", "email": current_user.email}


@router.get("/odontologo-only")
def odontologo_only(current_user: User = Depends(require_odontologo)):
    return {"message": "Access granted for odontologo", "email": current_user.email}
