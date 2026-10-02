# Design: C-01-foundation-setup

## Context
Greenfield total: el repo no tiene `backend/`, `frontend/`, `docker-compose.yml` ni CI. KB 08 §Estructura fija el árbol; DD-02 fija el stack; DD-01 exige monolito modular single-clínica con capas que permitan evolucionar a multi-tenant. Se diseña solo lo necesario para que C-02 modele sin retrabajo.

## Decisions
1. **Monolito modular con 5 paquetes backend (`domain/application/infrastructure/api/core`)** — por qué: lo exige 08 y prepara multi-tenant (DD-01) sin pagar microservicios en v1. Alternativa (flat `main.py` + routers sueltos): descartada, obligaría a reestructurar en C-02. Trade-off: 5 `__init__.py` vacíos iniciales.
2. **Prefijo global `/api`** — el health vive en `GET /api/health` (no `/health`), para que el futuro `app.frontend("/", directory="dist")` (regla fastapi skill) no colisione con la SPA servida estática.
3. **`core/settings.py` con pydantic-settings + 6 vars, timezone default BA, secretos sin default** — por qué: cumple Seguridad 08 (secrets solo por env) y deja SU-01/CANCEL y WA proveedor parametrizados. `CLINIC_TIMEZONE=America/Argentina/Buenos_Aires` y `CANCEL_MIN_HOURS=24` sí tienen default no-sensible; las 4 sensibles fallan si faltan.
4. **`def` síncrono por defecto; `async` prohibido en C-01** — el health y `get_db` no tienen llamadas no-bloqueantes reales; evita violar la regla dura async desde el día 1. Cuando haya I/O verdaderamente async (C-08 WA/Redis) se revisa con Asyncer.
5. **Alembic desde C-01 aunque sin tablas** — inicializar `env.py` + `versions/` vacío cuesta poco y garantiza que C-02/C-04 creen migraciones numeradas (001, 002…) como diff revisable. Alternativa (patear Alembic a C-02): descartada, C-02 quedaría bloqueado por infra.
6. **Compose v2 con healthchecks + `depends_on: condition: service_healthy`, `postgres:15-alpine` + `redis:7-alpine`, sin `ports:` en postgres/redis** — por qué: reglas docker-skills del registry (ordering por health, red por nombre, `restart: unless-stopped`). Solo `api:8000` y `web:5173` exponen puertos. Multi-env futuro vía `compose.override.yml`/`compose.prod.yml` (C-11), no ahora.
7. **Frontend: Vite + Zustand + api client tipado, Tailwind, `tsc --noEmit` en CI** — Zustand (no Redux) por estado de sesión simple; client centralizado evita URLs hardcodeadas y waterfalls futuros (`Promise.all` cuando haya múltiples fetches en C-09/C-10). `tsconfig` estricto desde el inicio para que la regla `no any` sea estructural, no revisada a mano.
8. **CI en 2 jobs paralelos sin tests de dominio** — C-01 solo exige smoke: `pytest` (al menos 1 test `test_health_ok` + 1 test `test_settings_timezone_default`, TDD) y `tsc + build`. Los tests de constraints/seed llegan en C-02.

## Cumplimiento de reglas duras (8/8 por diseño)
| # | Regla | Cómo se cumple en C-01 |
|---|---|---|
| 1 | Pydantic estricto + response_model | `HealthResponse(status: Literal["ok"])` + `response_model=` en el router; settings con tipos y validación |
| 2 | async correcto | `def` en health/deps; documentado en design; CI no exige async |
| 3 | Anti-solape en DB, no solo app | N/A sin modelo; hook dejado: Postgres 15 + Alembic listo para exclusion constraint en C-04 |
| 4 | TS estricto, no any, PascalCase | `tsconfig strict + noUncheckedIndexedAccess`; lint `no-explicit-any`; componentes PascalCase |
| 5 | No commit/push sin pedido | CI solo verifica; ningún step commitea |
| 6 | Modelo solo con migración versionada | `alembic/versions/` + convención `001_*.py, 002_*.py` documentada para C-02+ |
| 7 | WA nunca en request, siempre job Redis | Sin WA en C-01; servicio redis + `WA_PROVIDER_API_KEY` placeholder preparan C-08 |
| 8 | Datos sintéticos, nunca reales | Sin seeds en C-01; `.env.example` con placeholders; regla repetida en tasks |

## Risks
- **Deriva de versiones** (FastAPI/SQLAlchemy/Vite/Tailwind) → fijar rangos mínimos del stack + `pip freeze`/`package-lock` en repo; CI lo detecta.
- **Puertos/DB locales colisionando con Postgres del host** → postgres sin `ports:` por defecto; override local opcional documentado.
- **Zona horaria** (`timestamptz` + BA) mal asumida en dev Windows → `CLINIC_TIMEZONE` centralizado en settings y test que lo aserta; RN-GL-02 se implementa en C-04.
- **Frontend que hardcodea `localhost:8000`** → `VITE_API_BASE_URL` por env + client único; CI build lo valida.

## Project Standards (auto-resolved desde `.atl/skill-registry.md`)
- `fastapi`: estilo `Annotated`, `response_model`/return type siempre, `def` por defecto, `fastapi dev/run`, servir SPA vía `app.frontend`, nunca ORJSONRootModel/`...` defaults.
- `docker-skills (compose)`: `docker compose` (espacio), healthcheck en todo servicio dependido, `depends_on` con `service_healthy`, `.env` + `.env.example`, `docker compose config` para validar.
- `test-driven-development`: RED (test failing primero) → GREEN mínimo → TRIANGULATE (≥2 casos) → REFACTOR; suite verde completa.
- `vercel-react-best-practices`: paralelizar fetches, imports directos sin barrels, componentes pesados con dynamic, `cn()`/variantes semánticas cuando entre shadcn (no obligatorio en C-01).
