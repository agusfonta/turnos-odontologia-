# Tasks

## 1. Backend JWT & Password Utilities

- [x] 1.1 Implement password hashing and verification utilities using passlib/bcrypt and verify unit tests pass
- [x] 1.2 Implement JWT token creation and validation utilities for access and refresh tokens and verify unit tests pass

## 2. Backend Auth Endpoints & Rate Limiting

- [x] 2.1 Implement Redis-backed rate limiter for login attempts (3 requests / 5 minutes per IP+email) returning HTTP 429 Too Many Requests during the block period and verify rate limit tests pass
- [x] 2.2 Implement authentication endpoints (`POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout`, `GET /api/auth/me`) with token blacklisting and verify integration tests pass

## 3. RBAC Dependencies & Middleware

- [x] 3.1 Implement FastAPI permission dependencies (`require_role`, `require_secretaria`, `require_odontologo`) extracting roles from JWT claims and verify dependency tests pass

## 4. Frontend Auth Store, Login Page & Guards

- [x] 4.1 Implement Zustand authentication store and token management helpers and verify store unit tests pass
- [x] 4.2 Implement Login UI page, form validation, and React route guards and verify component rendering and redirection tests pass

## 5. Integration & Security Verification

- [x] 5.1 Run full end-to-end integration test suite covering successful login, token expiration, rate limiting, refresh rotation, and RBAC 403 authorization denials, verifying all tests pass successfully
