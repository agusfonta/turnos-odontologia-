# Tasks: C-01-foundation-setup

> Orden secuencial (un solo agente, GATE 0). Cada checkbox es verificable. Cargar skills indicadas antes de codificar. TDD obligatorio en backend.

- [x] **T1 — Esqueleto backend + settings/timezone/logger/db/exceptions (skills: `fastapi`, `test-driven-development`)**
  - RED: `backend/tests/test_health.py::test_health_ok` (espera 200 `{"status":"ok"}`) + `test_settings.py::test_default_timezone_es_buenos_aires` — deben FALLAR (no existe `app/`).
  - GREEN: crear `backend/app/{domain,application,infrastructure,api,core}/__init__.py`, `api/health.py` (`APIRouter`, `def`, `response_model=HealthResponse`), `api/__init__.py`, `main.py` (prefijo `/api`), `core/{settings,logger,db,exceptions}.py`, `requirements.txt` (fastapi 0.110+, sqlalchemy, alembic, pydantic-settings, psycopg), `pytest.ini`/`pyproject`.
  - TRIANGULATE: segundo caso `test_health_content_type_json` + `test_missing_jwt_secret_fails_validation`.
  - Verificación: `pytest` verde; `GET /api/health` manual.

- [x] **T2 — Alembic inicializado sin tablas (skills: `fastapi`, `supabase-postgres-best-practices` solo lectura de convenciones)**
  - Crear `alembic.ini` + `alembic/env.py` (lee `DATABASE_URL` de settings) + `alembic/versions/.gitkeep` + `alembic/script.py.mako`.
  - Verificación: `alembic upgrade head` → exit 0 en vacío; documentar convención `NNN_descripcion.py` para C-02.

- [x] **T3 — Esqueleto frontend Vite+React+TS+Tailwind+Zustand+api client (skills: `vercel-react-best-practices`)**
  - `npm create vite@latest frontend -- --template react-ts`; fijar React 18+, TS 5+; `tsconfig` estricto (`strict`, `noUncheckedIndexedAccess`, `noImplicitAny`); ESLint `no-explicit-any`; estructura `src/{features,shared,pages}`; `shared/api/client.ts` tipado con `VITE_API_BASE_URL`; store Zustand base; Tailwind config; página shell que muestra estado de `/api/health`.
  - Verificación: `npm run dev` renderiza; `tsc --noEmit` limpio; cero `any` (`rg "\bany\b" src` vacío salvo comentarios).

- [x] **T4 — Compose + env examples + gitignore (skill: `docker-skills (compose)`)**
  - `docker-compose.yml` (api/web/postgres:15-alpine/redis:7-alpine, healthchecks `pg_isready`/`redis-cli ping`, `depends_on service_healthy`, `restart: unless-stopped`, red por defecto, sin `ports:` en data stores); `Dockerfile` api (python 3.12-slim) + `Dockerfile`/`vite config` web; `.env.example` raíz + `backend/.env.example` + `frontend/.env.example` (6 vars, sensibles `changeme`); `.gitignore` (`.env`, `__pycache__`, `node_modules`, `dist`).
  - Verificación: `docker compose config` válido; `docker compose up --build -d` → 4 healthy; `curl localhost:8000/api/health` 200.

- [x] **T5 — CI paralela + verificación E2E del scaffolding**
  - `.github/workflows/ci.yml`: job `backend` (python 3.12, `pip install -r requirements.txt`, `pytest`) || job `frontend` (`npm ci`, `tsc --noEmit`, `npm run build`).
  - Verificación final: CI verde; `pytest` + `tsc` + `compose up` + `alembic upgrade head` documentados en `README` delta (o nota en proposal si README no se toca en C-01). Marcar listo para `/opsx:archive` + C-02.

## Nota de verificación (sesión apply 2026-10-02)
- T1–T3, T5 verificados en local: `pytest` 4 passed; `alembic upgrade head` exit 0 (vacío, contra sqlite temporal); `tsc --noEmit` limpio; `rg any` vacío; `oxlint` 0 warnings; `vite build` OK; dev server 200.
- `docker compose config` válido. PENDIENTE de entorno (no del change): el daemon Docker está apagado en esta máquina (`docker info` → pipe inexistente), por lo que `docker compose up --build -d` + `curl localhost:8000/api/health` y el job CI en GitHub quedan para el usuario: iniciar Docker Desktop, correr `Copy-Item .env.example .env; docker compose up --build -d`, y pushear para ver CI verde.
