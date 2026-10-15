# Spec Delta

## Purpose

Provides secure authentication using JWT access and refresh tokens, token revocation, IP+email rate limiting, and Role-Based Access Control enforcing secretaria and odontologo roles.

## ADDED Requirements

### Requirement: JWT Login Authentication
The system SHALL validate user credentials against the database and issue a short-lived JWT access token and an HttpOnly refresh token cookie upon successful login.

#### Scenario: Successful login with valid credentials
- **WHEN** a user submits valid email and password to `POST /api/auth/login`
- **THEN** the system returns a JWT access token in the response body and sets an HttpOnly, Secure, SameSite=Lax cookie containing the refresh token

#### Scenario: Failed login with invalid credentials
- **WHEN** a user submits incorrect password or non-existent email to `POST /api/auth/login`
- **THEN** the system returns HTTP 401 Unauthorized

### Requirement: Refresh Token Rotation and Revocation
The system SHALL rotate refresh tokens upon request, issuing a new access and refresh token pair while invalidating the previous refresh token.

#### Scenario: Successful token refresh
- **WHEN** a valid refresh token is submitted to `POST /api/auth/refresh`
- **THEN** the system issues a new access token and a new refresh token, blacklisting the old refresh token

#### Scenario: Attempt to reuse a blacklisted refresh token
- **WHEN** a previously used or revoked refresh token is submitted to `POST /api/auth/refresh`
- **THEN** the system rejects the request with HTTP 401 Unauthorized

### Requirement: Access Token Blacklist Logout
The system SHALL invalidate access tokens upon logout by adding their unique identifier (`jti`) to a blacklist cache.

#### Scenario: Successful logout
- **WHEN** an authenticated user calls `POST /api/auth/logout` with a valid access token
- **THEN** the access token's `jti` is added to the blacklist and the response returns HTTP 200 OK

### Requirement: Rate Limiting on Login
The system SHALL limit login attempts to protect against brute-force attacks by enforcing a maximum number of attempts per IP address and email combination, returning HTTP 429 Too Many Requests during the block period.

#### Scenario: Rate limit exceeded
- **WHEN** more than 3 login attempts occur within 5 minutes from the same IP address and email combination
- **THEN** the system rejects subsequent attempts with HTTP 429 Too Many Requests

### Requirement: Role-Based Access Control (RBAC)
The system SHALL enforce role-based access control via dependency injection (`require_role`, `require_secretaria`, `require_odontologo`) based on user roles stored in JWT claims.

#### Scenario: Authorized access for Secretaria role
- **WHEN** a user with the `secretaria` role accesses an endpoint guarded by `require_secretaria`
- **THEN** the request is allowed to proceed

#### Scenario: Unauthorized access denial
- **WHEN** a user without the required role attempts to access a guarded endpoint
- **THEN** the system returns HTTP 403 Forbidden
