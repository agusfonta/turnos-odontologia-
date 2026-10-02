# Spec: foundation (delta — capability nueva)

## ADDED Requirements

### BACKEND scaffolding
- **MUST** existir `backend/app/{domain,application,infrastructure,api,core}/__init__.py` más `backend/app/main.py` que monte el router bajo prefijo `/api` y exponga `GET /api/health` → 200 con schema estricto `{"status": "ok"}` (response_model obligatorio, sin campos fantasma).
- **MUST** existir `backend/app/core/settings.py` (pydantic-settings) que lea exactamente `DATABASE_URL, REDIS_URL, JWT_SECRET, WA_PROVIDER_API_KEY, CLINIC_TIMEZONE, CANCEL_MIN_HOURS`; `CLINIC_TIMEZONE` default `America/Argentina/Buenos_Aires`, `CANCEL_MIN_HOURS` default `24`; ningún secreto con default real (JWT/WA/URLs sin default o placeholder vacío que falle en validación si falta en prod).
- **MUST** existir `core/logger.py` (logging estructurado base), `core/db.py` (engine/session SQLAlchemy + `get_db` dependency) y `core/exceptions.py` (jerarquía `AppError` + handlers globales que devuelven problem+json consistente).
- **MUST** estar Alembic inicializado (`alembic.ini` + `alembic/env.py` leyendo `DATABASE_URL` + `alembic/versions/.gitkeep`); `alembic upgrade head` en vacío **MUST** terminar 0.
- **MUST** `def` por defecto en endpoints/dependencies; `async def` solo si todo el cuerpo es no-bloqueante.

### FRONTEND scaffolding
- **MUST** existir proyecto Vite + React 18 + TS 5 con `tsconfig` estricto (`strict: true`, `noUncheckedIndexedAccess: true`), `noImplicitAny`, cero `any` explícito; componentes en PascalCase.
- **MUST** existir estructura `src/{features,shared,pages}` + `shared/api/client.ts` (fetch/HttpClient tipado con `API_BASE_URL` por env, sin URLs hardcodeadas) + store Zustand base de sesión placeholder (sin auth real).
- **MUST** incluir Tailwind configurado y página shell mínima que renderiza y consume `GET /api/health` mostrando estado.

### INFRA / CI
- **MUST** `docker-compose.yml` (Compose v2, `docker compose`) con 4 servicios: `api` (build backend, puerto 8000, `depends_on` postgres+redis con `condition: service_healthy`), `web` (build frontend o dev server, puerto 5173), `postgres` (imagen `postgres:15-alpine`, healthcheck `pg_isready`, volumen persistente, SIN puertos publicados salvo override local), `redis` (imagen `redis:7-alpine`, healthcheck `redis-cli ping`); red por defecto (los pares se alcanzan por nombre de servicio); `restart: unless-stopped`; `.env` nunca commiteado (`.gitignore` + `.env.example` con placeholders).
- **MUST** `.env.example` en raíz y por sub-proyecto (`backend/.env.example`, `frontend/.env.example`) documentando las 6 vars; valores sensibles siempre `changeme`/vacío.
- **MUST** `.github/workflows/ci.yml` con jobs paralelos: `backend` (`pip install` + `pytest`) y `frontend` (`npm ci` + `tsc --noEmit` + `npm run build`).
- **MUST** todo fixture/ejemplo usar datos sintéticos/anónimos; ningún dato real de paciente en repo.

## Out of scope (explicitamente NO en C-01)
Tablas, migraciones con modelo, seeds, JWT/RBAC, turnos/disponibilidad/bloqueos/auditoría, worker WA, páginas `/reservar` `/agenda` `/turnos/:token`, prod compose.
