# Proposal: c-02-modelos-core-y-seed

## Why
C-03 (auth/RBAC) necesita `users`, C-04 (disponibilidad/reserva) necesita `profesionales`, `pacientes` y `tratamientos` con duraciones para calcular huecos (RN-AG-03), y US-002/004/006 dependen de estas tablas. Hoy `backend/app/{domain,infrastructure}/` están vacíos y `alembic/versions/` no tiene ninguna migración: sin este change todo el camino crítico está bloqueado. Además fija los patrones de persistencia (`AuditMixin`, `BaseRepository[T]`, `UnitOfWork`) que el resto de los changes reutiliza.

## What (scope CHANGES.md, autoritativo)
- Modelos: `User` (roles `secretaria`/`odontologo`, sin rol paciente), `Profesional` (matrícula única, `activo`, `slot_default_min`), `Paciente` (teléfono E.164, índice en teléfono), `Tratamiento` (`duracion_min > 0`, `activo`).
- `AuditMixin` con `is_active`, `created_at`, `updated_at`, `deleted_at` (soft delete).
- `BaseRepository[T]` genérico + `UnitOfWork` (sesión sincrónica, commit/rollback).
- Migración `001`: tablas `users`, `profesionales`, `pacientes`, `tratamientos` (upgrade + downgrade completos).
- Seed mínimo idempotente: 1 secretaria, 1 profesional ejemplo, 3 tratamientos (limpieza 30m, consulta 20m, conducto 60m), parámetro `CANCEL_MIN_HOURS=24` leído de settings (no hardcodeado).
- Tests: constraints (matrícula única, teléfono válido, duración > 0), seed idempotente (doble corrida sin duplicar).
- Governance CRÍTICO (datos + base de auth). Dependencia: C-01 archivada ✓.

## Non-goals
- `Turno`, `Bloqueo`, `Notificacion`, `AuditoriaTurno` y sus migraciones/índices (C-04 migración 002, C-08 migración 003).
- Exclusion constraint anti-solape (es sobre `turno`, llega en C-04 con RN-AG-01).
- Endpoints, routers, schemas HTTP, JWT/RBAC, hashing de login/verify (C-03; C-02 solo deja `password_hash` + hash para el seed).
- Tabla de parámetros: `CANCEL_MIN_HOURS` vive en settings/env, no en DB (YAGNI; edición runtime sería change futuro).
- Worker Redis, proveedor WhatsApp (C-08). Frontend (sin cambios). Multi-tenant (DD-01: change futuro).

## Assumptions
- Pregunta Alta "¿login paciente o nombre+teléfono?" → **resuelta por DD-03**: reserva pública sin login; `User` es solo staff (`secretaria`/`odontologo`). El paciente nunca tiene credenciales en v1.
- Pregunta Alta "¿anticipación 24h o 2–3h?" → **parametrizada (SU-01)**: seed lee `CANCEL_MIN_HOURS` de settings (default 24); la clínica la confirma antes de C-05, sin cambiar código.
- Pregunta Media "¿duraciones fijas por tratamiento?" → **sí**: `Tratamiento.duracion_min` entra en 001 (RN-AG-03 lo exige para huecos).
- Pregunta Media "¿sillones compartidos?" → **no en v1 (SU-03)**: sin columna de recurso físico; si la clínica lo desmiente, será migración dedicada.
- Pregunta Media "¿deduplicación por teléfono/DNI?" → **diferida**: en 001 teléfono lleva índice pero NO unique (trade-off DD-03: se acepta posible duplicación); la regla de dedup se define en C-05 y se endurece en C-11 si corresponde.
- Email de `User` se normaliza a minúsculas en app (unique case-sensitive en DB, sin extensión CITEXT).
- UUIDs con default en app (`uuid4`), sin extensión `pgcrypto`, para que la migración corra en cualquier Postgres 15 y los tests no dependan de superusuario.

## Success criteria
- `alembic upgrade head` crea las 4 tablas con constraints/índices; `alembic downgrade -1` las revierte limpio.
- Seed corrido 2 veces deja exactamente 1 secretaria, 1 profesional, 3 tratamientos (conteos idénticos, cero duplicados).
- `pytest` verde incluyendo tests de constraints y de seed; CI backend con servicio Postgres en verde.
- C-03 puede implementar login contra `users` y C-04 puede referenciar las 4 tablas sin retrabajo del modelo.
