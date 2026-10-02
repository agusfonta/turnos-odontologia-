# foundation Specification

## Purpose
Provee el scaffolding base del monorepo (backend FastAPI, frontend Vite + React, Compose local y CI paralela) sobre el que se construyen los changes C-02 a C-11 sin retrabajo de estructura.

## Requirements

### Requirement: Backend scaffolding
The system SHALL provide the backend base layout `backend/app/{domain,application,infrastructure,api,core}` with `main.py` mounting the router under `/api` and exposing `GET /api/health` returning 200 with strict schema `{"status": "ok"}` (response_model obligatorio, sin campos fantasma). Settings SHALL be read via pydantic-settings from exactly `DATABASE_URL, REDIS_URL, JWT_SECRET, WA_PROVIDER_API_KEY, CLINIC_TIMEZONE, CANCEL_MIN_HOURS`, with `CLINIC_TIMEZONE` default `America/Argentina/Buenos_Aires` and `CANCEL_MIN_HOURS` default `24`, and no real default for secrets. The system SHALL include structured base logging, SQLAlchemy engine/session with `get_db` dependency, and global `AppError` handlers returning consistent problem+json. Alembic SHALL be initialized (`alembic.ini` + `alembic/env.py` reading `DATABASE_URL` + `alembic/versions/.gitkeep`). Endpoints and dependencies SHALL use `def` by default and `async def` only when the whole body is non-blocking.

#### Scenario: Health check responde 200 con schema estricto
- **WHEN** a client calls `GET /api/health`
- **THEN** the system responds 200 with body `{"status": "ok"}` and no extra fields

#### Scenario: Migracion en vacio termina en cero
- **WHEN** `alembic upgrade head` runs against an empty database
- **THEN** it exits 0 without errors

### Requirement: Frontend scaffolding
The system SHALL provide a Vite + React 18 + TS 5 project with strict `tsconfig` (`strict: true`, `noUncheckedIndexedAccess: true`), no implicit or explicit `any`, and PascalCase components. It SHALL include the `src/{features,shared,pages}` structure plus a typed fetch client in `shared/api/client.ts` using `API_BASE_URL` from env (no hardcoded URLs) and a placeholder Zustand session store (no real auth). Tailwind SHALL be configured and a minimal shell page SHALL render and consume `GET /api/health` showing its status.

#### Scenario: Shell consume health y muestra estado
- **WHEN** the shell page loads
- **THEN** it calls `GET /api/health` and displays the returned status

### Requirement: Infraestructura local y CI
The system SHALL provide a `docker-compose.yml` (Compose v2, `docker compose`) with 4 services: `api` (backend build, port 8000, `depends_on` postgres+redis with `condition: service_healthy`), `web` (frontend build or dev server, port 5173), `postgres` (`postgres:15-alpine`, `pg_isready` healthcheck, persistent volume, no published ports except local override), `redis` (`redis:7-alpine`, `redis-cli ping` healthcheck); default network (peers reachable by service name); `restart: unless-stopped`; `.env` never committed (`.gitignore` + `.env.example` with placeholders). Root and per-subproject `.env.example` files SHALL document the 6 vars with `changeme`/empty values for sensitive ones. A `.github/workflows/ci.yml` SHALL run parallel jobs: `backend` (`pip install` + `pytest`) and `frontend` (`npm ci` + `tsc --noEmit` + `npm run build`). All fixtures and examples SHALL use synthetic/anonymous data; no real patient data in the repo.

#### Scenario: Compose levanta 4 servicios sanos
- **WHEN** `docker compose up --build` runs
- **THEN** `api`, `web`, `postgres` and `redis` reach healthy state and `GET /api/health` returns 200 `{"status": "ok"}`

#### Scenario: CI paralela en verde
- **WHEN** CI runs on a push
- **THEN** the backend job and the frontend job both pass

#### Scenario: Fixtures solo con datos sinteticos
- **WHEN** fixtures or examples are added to the repo
- **THEN** they contain only synthetic or anonymous data
