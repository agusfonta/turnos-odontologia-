# Design

## Context

- **Current State**: C-02 established the database models (including `users` table with `password_hash`, `email`, and `user_role` enum `secretaria`/`odontologo`).
- **Constraints**: FastAPI backend, Python 3.12, Pydantic v2 strict models, Redis 7 for blacklisting and rate limiting, React/Zustand frontend foundation.

## Goals / Non-Goals

**Goals:**
- Implement stateless JWT access validation with stateful refresh token rotation and revocation.
- Provide clean FastAPI dependencies (`require_secretaria`, `require_odontologo`, `require_role`) for RBAC.
- Enforce IP+email rate limiting on login via Redis.
- Secure refresh token delivery using HttpOnly, Secure, SameSite=Lax cookies.

**Non-Goals:**
- OAuth2 social login (Google, Microsoft) - out of scope for v1.
- Multi-factor authentication (MFA) - deferred to later iterations.

## Decisions

- **JWT Library**: Use `python-jose` (or `PyJWT`) with `bcrypt` / `passlib` for password hashing, aligning with FastAPI standard security practices.
- **Token Lifetimes**: Short-lived Access Token (e.g., 15-30 minutes) and longer-lived Refresh Token (e.g., 7 days) with sliding rotation.
- **Revocation & Rate Limiting**: Store access token `jti` blacklist and refresh token rotation state in Redis with TTL matching token expiration. Use Redis rate limiting enforcing a maximum of 3 attempts per 5 minutes per IP+email combination, returning HTTP 429 Too Many Requests during the block period.
- **Frontend State**: Zustand store managing session tokens and user roles in memory, protected route wrappers in React router.

## Risks / Trade-offs

- **Redis Dependency**: Authentication dependency relies on Redis being available for rate limiting and blacklists.
  - *Mitigation*: Fail gracefully or fallback to memory cache if Redis is temporarily unreachable in dev, but enforce strict Redis dependency in production config.
- **Token Expiry Sync**: Client clock skew affecting JWT expiration.
  - *Mitigation*: Use standard short lifetimes and automatic refresh via Axios interceptors.

## Migration Plan

1. Ensure environment variables (`JWT_SECRET_KEY`, `JWT_REFRESH_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`) are configured in `.env`.
2. Deploy backend authentication routes and dependencies.
3. Deploy frontend login page and auth store integration.
