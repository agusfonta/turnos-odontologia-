# Proposal: C-01-foundation-setup

## Why
Sin scaffolding no hay camino crítico: C-02→C-11 cuelgan de una base que hoy no existe (repo solo con `knowledge-base/`, `CHANGES.md`, `openspec/` vacíos). Este change crea el monorepo modular single-clínica (DD-01) con el stack impuesto (DD-02) y la infraestructura local mínima para desarrollar y verificar cada change posterior con CI paralela.

## What (scope CHANGES.md, autoritativo)
- Estructura `backend/app/{domain,application,infrastructure,api,core}` + `frontend/src/{features,shared,pages}` según KB 08.
- Backend: FastAPI mínima con `GET /api/health`, Alembic inicializado, `core/` con settings (zona `America/Argentina/Buenos_Aires`), logger, db, exceptions.
- Frontend: Vite + React 18 + TS 5 + Tailwind + Zustand + api client base.
- `docker-compose.yml`: servicios `api` + `web` + `postgres 15` + `redis 7`.
- `.env.example` por sub-proyecto: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `WA_PROVIDER_API_KEY`, `CLINIC_TIMEZONE`, `CANCEL_MIN_HOURS` (sin defaults sensibles hardcodeados).
- GitHub Actions CI con jobs paralelos `backend` (pytest) y `frontend` (tsc + build).
- Governance BAJO. Sin dependencias.

## Non-goals
- Ningún modelo de dominio, migración de tablas, seed, auth/RBAC, turnos, bloqueos, notificaciones ni páginas de reserva/agenda (todo C-02→C-10).
- Sin proveedor WhatsApp real, sin worker Redis (solo servicio + env placeholder para C-08).
- Sin `docker-compose.prod.yml` ni hardening (C-11). Sin multi-tenant (DD-01: change futuro dedicado).

## Assumptions
- Supuestos SU-01 (anticipación default 24h configurable), SU-02 (Redis solo jobs en v1), SU-03 (1 sillón = 1 profesional) se aceptan como placeholders configurables; su validación con la clínica ocurre antes de C-02/C-04.
- Las 3 preguntas de prioridad Alta de `10_preguntas_abiertas.md` quedan parametrizadas, no resueltas, en este change.
- Versiones mínimas: Python 3.12, FastAPI 0.110+, Postgres 15, Redis 7, React 18+, TS 5+, Compose v2.

## Success criteria
- `docker compose up --build` levanta 4 servicios; `GET /api/health` → 200 `{"status":"ok"}`; `web` sirve el shell Vite.
- `alembic upgrade head` corre en vacío sin error (estructura `versions/` lista).
- CI en verde con los dos jobs paralelos. C-02 puede arrancar sin retrabajo de estructura.
