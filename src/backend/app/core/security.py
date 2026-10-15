"""Seguridad, hashing, JWT access/refresh tokens, token blacklisting y rate limiting con Redis (C-03)."""

from datetime import datetime, timedelta, timezone
import uuid
from fastapi import HTTPException, status
from jose import JWTError, jwt
import redis
from passlib.context import CryptContext

from app.core.settings import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def get_redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str, email: str, rol: str, expires_delta: timedelta | None = None
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    jti = str(uuid.uuid4())
    payload = {
        "sub": subject,
        "email": email,
        "rol": rol,
        "type": "access",
        "jti": jti,
        "iat": datetime.now(timezone.utc).timestamp(),
        "exp": expire.timestamp(),
    }
    encoded_jwt = jwt.encode(
        payload, settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    jti = str(uuid.uuid4())
    secret = (
        settings.JWT_REFRESH_SECRET.get_secret_value()
        if settings.JWT_REFRESH_SECRET
        else settings.JWT_SECRET.get_secret_value()
    )
    payload = {
        "sub": subject,
        "type": "refresh",
        "jti": jti,
        "iat": datetime.now(timezone.utc).timestamp(),
        "exp": expire.timestamp(),
    }
    encoded_jwt = jwt.encode(payload, secret, algorithm=ALGORITHM)
    return encoded_jwt


def is_token_blacklisted(jti: str) -> bool:
    try:
        r = get_redis_client()
        return bool(r.get(f"blacklist:{jti}"))
    except Exception:
        # Fallback if Redis is unavailable in testing or dev without strict Redis
        return False


def blacklist_token(jti: str, expires_in_seconds: int = 86400) -> None:
    try:
        r = get_redis_client()
        r.setex(f"blacklist:{jti}", expires_in_seconds, "revoked")
    except Exception:
        pass


def decode_token(token: str, token_type: str = "access") -> dict:
    settings = get_settings()
    secret = (
        settings.JWT_REFRESH_SECRET.get_secret_value()
        if token_type == "refresh" and settings.JWT_REFRESH_SECRET
        else settings.JWT_SECRET.get_secret_value()
    )
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        if payload.get("type") != token_type:
            raise credentials_exception
        jti = payload.get("jti")
        if jti and is_token_blacklisted(jti):
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


def check_login_rate_limit(ip: str, email: str, max_attempts: int = 3, window_seconds: int = 300) -> None:
    """Rate limit: max 3 attempts per 5 minutes per IP+email. Returns 429 if blocked."""
    key = f"ratelimit:login:{ip}:{email.lower()}"
    try:
        r = get_redis_client()
        attempts = r.get(key)
        if attempts is not None and int(attempts) >= max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos fallidos. Intente nuevamente en 5 minutos.",
            )
    except HTTPException:
        raise
    except Exception:
        # If Redis fails, allow request but log/pass
        pass


def record_failed_login(ip: str, email: str, window_seconds: int = 300) -> None:
    key = f"ratelimit:login:{ip}:{email.lower()}"
    try:
        r = get_redis_client()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        pipe.execute()
    except Exception:
        pass


def clear_login_rate_limit(ip: str, email: str) -> None:
    key = f"ratelimit:login:{ip}:{email.lower()}"
    try:
        r = get_redis_client()
        r.delete(key)
    except Exception:
        pass
