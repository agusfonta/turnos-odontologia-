"""Dependencias FastAPI de autenticación y RBAC (C-03)."""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_token
from app.infrastructure.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    payload = decode_token(token, token_type="access")
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
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
    return user


def require_role(required_role: str):
    def role_dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.rol.value != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for this role",
            )
        return current_user
    return role_dependency


require_secretaria = require_role("secretaria")
require_odontologo = require_role("odontologo")


def require_staff(current_user: User = Depends(get_current_user)) -> User:
    """Usuario autenticado con rol `secretaria` u `odontologo` (agenda interna, C-06)."""
    if current_user.rol.value not in ("secretaria", "odontologo"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role",
        )
    return current_user


oauth2_scheme_opcional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_optional_staff(
    token: Annotated[str | None, Depends(oauth2_scheme_opcional)],
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User | None:
    """Reserva publica o de secretaria (C-04, design Decision 8).

    Sin header `Authorization` -> `None` (publico). Con header: se reutiliza
    la validacion de `get_current_user` (401 si invalido/expirado) y se exige
    rol `secretaria` (403). NUNCA se degrada a publico ante un header presente
    pero invalido (incluye esquema no Bearer o token vacio, que
    `auto_error=False` reportaria como `None`).
    """
    if token is None:
        if authorization is None:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = get_current_user(token, db)
    if user.rol.value != "secretaria":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role",
        )
    return user
