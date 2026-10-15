# Proposal

## Why

To establish secure access control and authentication across the platform, we need robust JWT authentication with refresh token rotation, token blacklisting, IP+email rate limiting, and Role-Based Access Control (RBAC) enforcing secretaria and odontologo permissions. This fulfills C-03 requirements and secures all subsequent backend and frontend endpoints.

## What Changes

- **Authentication Endpoints**:
  - `POST /api/auth/login`: Validates user credentials against hashed passwords in the `users` table, returns a short-lived JWT access token, sets an HttpOnly secure cookie with the refresh token, and enforces rate limiting (3 attempts per 5 minutes per IP+email, returning HTTP 429 Too Many Requests during the block period).
  - `POST /api/auth/refresh`: Rotates the refresh token, revokes/blacklists the old refresh token, and issues a new access/refresh token pair.
  - `POST /api/auth/logout`: Blacklists the active access token and clears session state.
  - `GET /api/auth/me`: Returns authenticated user profile and roles.
- **Authorization / RBAC**:
  - FastAPI dependency context (`require_role`, `require_secretaria`, `require_odontologo`) enforcing role constraints against user roles stored in JWT claims and database.
- **JWT Claim Structure**:
  - Claims include `sub`, `roles`, `email`, `jti`, `type`, `iat`, and `exp`.
- **Frontend Foundation**:
  - Login page, route guards, and Zustand session store (preparing the base for C-10).
- **Testing**:
  - Automated unit and integration tests for successful login, expired tokens, rate limiting violations, refresh rotation, and RBAC 403 permission denials.

## Capabilities

### New Capabilities
- `auth`: JWT authentication, token rotation, blacklisting, rate-limiting, and RBAC dependency injection.

### Modified Capabilities
- None.

## Impact

- **Backend**: FastAPI routes, security dependencies, Redis/DB storage for blacklisted tokens/rate limits.
- **Frontend**: Login UI components, route protection wrappers, auth store.
- **Security**: Hardened entry points preventing brute-force attacks and unauthorized role escalation.
