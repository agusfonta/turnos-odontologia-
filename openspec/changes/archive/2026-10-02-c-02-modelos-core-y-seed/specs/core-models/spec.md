# Spec: core-models (delta — capability nueva)

## ADDED Requirements

### Identidad y auditoría base
- **MUST** existir `AuditMixin` (en `domain/` o `infrastructure/`) con columnas `is_active BOOLEAN NOT NULL DEFAULT true`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `deleted_at TIMESTAMPTZ NULL`; el borrado lógico **MUST** setear `is_active=false` + `deleted_at=now()` y los listados del repositorio **MUST** excluir inactivos por defecto.
- **MUST** las 4 entidades usar PKs según KB 04: `User`/`Profesional`/`Paciente` con `id UUID PRIMARY KEY DEFAULT uuid4` (default en app, sin `pgcrypto`); `Tratamiento` con `id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`.

### User (staff-only)
- **MUST** la tabla `users` tener `email VARCHAR(320) NOT NULL UNIQUE` (normalizado a minúsculas en app), `password_hash TEXT NOT NULL`, `rol user_role NOT NULL` donde `user_role` es enum Postgres `('secretaria','odontologo')` — **MUST NOT** existir rol `paciente` en v1 (DD-03: el paciente opera sin login vía token por turno, C-04/C-07).
- **MUST** `User` incluir `AuditMixin` completo.

### Profesional
- **MUST** la tabla `profesionales` tener `nombre VARCHAR(200) NOT NULL`, `matricula VARCHAR(50) NOT NULL UNIQUE`, `especialidad VARCHAR(120) NULL`, `slot_default_min INTEGER NOT NULL DEFAULT 30 CHECK (slot_default_min > 0)`, más `AuditMixin`.
- **MUST** el flag de dominio `activo` (RN-TU-02: solo profesionales activos reciben turnos) **mapearse a `AuditMixin.is_active` sin columna duplicada**, con índice parcial `WHERE is_active = true` e índice en `especialidad`.

### Paciente
- **MUST** la tabla `pacientes` tener `nombre VARCHAR(200) NOT NULL`, `telefono VARCHAR(16) NOT NULL CHECK (telefono ~ '^\+[1-9][0-9]{7,14}$')` (E.164), `dni VARCHAR(16) NULL`, más `AuditMixin`.
- **MUST** existir índice btree no-único en `pacientes(telefono)`; **MUST NOT** haber constraint UNIQUE en teléfono en v1 (deduplicación diferida a C-05/C-11).
- **MUST** la validación E.164 existir también en capa app (Pydantic estricto) además del CHECK en DB (defensa en profundidad).

### Tratamiento
- **MUST** la tabla `tratamientos` tener `nombre VARCHAR(120) NOT NULL UNIQUE`, `duracion_min INTEGER NOT NULL CHECK (duracion_min > 0)`, más `AuditMixin` donde `is_active` es el flag `activo` del catálogo (sin columna duplicada), con índice parcial `WHERE is_active = true`.

### Persistencia e infra
- **MUST** existir `BaseRepository[T]` sincrónico (`get`, `list` paginado excluyendo inactivos por defecto, `add`, `soft_delete`) con tipos de retorno estrictos, y `UnitOfWork` con context manager (`commit`/`rollback`) sobre `Session` de `core/db.py`; **MUST** usar `def`, nunca `async def` (sin I/O no-bloqueante; regla dura async).
- **MUST** la migración `backend/alembic/versions/001_core_tables.py` (convención `NNN_*`, `down_revision=None`) crear enum + 4 tablas + checks + índices, escrita a mano como diff revisable, con `downgrade()` que revierte todo en orden inverso.
- **MUST** existir seed CLI idempotente (`run_seed`, NO auto-run en import/startup) con get-or-create por claves naturales (`users.email`, `profesionales.matricula`, `tratamientos.nombre`): 1 secretaria sintética, 1 profesional ejemplo ficticio, 3 tratamientos (limpieza 30, consulta 20, conducto 60); **MUST** leer `CANCEL_MIN_HOURS` de settings (SU-01, nunca hardcode) y **MUST** usar solo datos sintéticos (teléfonos de rango ficticio, dominio `example.test`).
- **MUST** el seed hashear con bcrypt (dependencia nueva) vía función mínima `hash_password()` en `core/security.py`; verify/login quedan en C-03.

#### Scenario: Seed idempotente
- **WHEN** el seed corre dos veces seguidas sobre la misma DB
- **THEN** los conteos de `users`, `profesionales` y `tratamientos` son idénticos tras ambas corridas y no hay duplicados por clave natural

#### Scenario: Constraints rechazan datos inválidos
- **WHEN** se inserta matrícula duplicada, teléfono no-E.164 o `duracion_min <= 0`
- **THEN** la DB rechaza la fila (UniqueViolation / CheckViolation) y la capa app valida antes con error tipado

## Out of scope (explícitamente NO en C-02)
Tablas `turno`/`bloqueo`/`auditoria_turno`/`notificacion`, exclusion constraint anti-solape, routers/endpoints, JWT/refresh/blacklist/RBAC, `verify_password`, worker Redis, `WAClient`, tabla de parámetros, frontend, `docker-compose.prod.yml`.
