# Turnos Odontología

Sistema de gestión de turnos para clínica odontológica (monolito modular single-clínica).

## Stack

Backend: Python + FastAPI + SQLAlchemy + Alembic · Postgres 15 · Redis 7.
Frontend: React + TypeScript + Vite + Tailwind + Zustand. Compose v2.

## Estructura

- `src/backend/app/{domain,application,infrastructure,api,core}` — API FastAPI (`/api/*`)
- `src/frontend/src/{features,shared,pages}` — SPA Vite (consume `VITE_API_BASE_URL`)
- `docker-compose.yml` — `api` :8000 + `web` :5173 + `postgres` + `redis`

## Quickstart (C-01)

```powershell
Copy-Item .env.example .env
docker compose up --build -d
curl http://localhost:8000/api/health   # -> {"status":"ok"}
```

## Verificación del scaffolding (C-01)

```powershell
# Backend (TDD: tests/test_health.py + tests/test_settings.py)
cd backend; pytest

# Migraciones en vacío
$env:DATABASE_URL="sqlite:///./.alembic-check.db"; $env:REDIS_URL="redis://localhost:6379/0"
$env:JWT_SECRET="check"; $env:WA_PROVIDER_API_KEY="check"
python -m alembic upgrade head

# Frontend
cd frontend; npm ci; npx tsc --noEmit -p tsconfig.app.json; npm run lint; npm run build

# Compose
docker compose config; docker compose up --build -d
```

Detalles de dominio: `knowledge-base/`. Plan: `CHANGES.md`.
