# core-models Specification

## Purpose
Provee las entidades base del dominio clinico (usuarios staff, profesionales, pacientes y tratamientos) con auditoria uniforme, persistencia transaccional y seed minimo idempotente, sobre las que se construyen los changes C-03 a C-11.

## Requirements

### Requirement: Identidad y auditoria base
The system SHALL provide an `AuditMixin` with columns `is_active BOOLEAN NOT NULL DEFAULT true`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` and `deleted_at TIMESTAMPTZ NULL`. Logical deletion SHALL set `is_active=false` plus `deleted_at=now()`, and repository listings SHALL exclude inactive rows by default. The 4 entities SHALL use PKs per KB 04: `User`, `Profesional` and `Paciente` with `id UUID PRIMARY KEY DEFAULT uuid4` (default generated in app, without `pgcrypto`); `Tratamiento` with `id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`.

#### Scenario: Borrado logico excluye de listados por defecto
- **WHEN** a record is soft-deleted through the repository
- **THEN** the system sets `is_active=false` and `deleted_at=now()` and default listings no longer include it

#### Scenario: PKs con defaults en app
- **WHEN** a `User`, `Profesional` or `Paciente` is created without an explicit id
- **THEN** the app generates a UUID default, and `Tratamiento` rows use the identity sequence

### Requirement: User staff-only
The system SHALL provide a `users` table with `email VARCHAR(320) NOT NULL UNIQUE` (normalized to lowercase in app), `password_hash TEXT NOT NULL` and `rol user_role NOT NULL`, where `user_role` is the Postgres enum `('secretaria','odontologo')`. There SHALL NOT be a `paciente` role in v1: the patient operates without login via per-appointment token (C-04/C-07). `User` SHALL include the full `AuditMixin`.

#### Scenario: Email normalizado y unico
- **WHEN** a user is created with an uppercase email or with an already registered email
- **THEN** the system stores it lowercased and rejects the duplicate with a uniqueness violation

#### Scenario: Sin rol paciente en v1
- **WHEN** a `User` is created with a role outside `('secretaria','odontologo')`
- **THEN** the system rejects it because the enum does not admit a `paciente` role

### Requirement: Profesional
The system SHALL provide a `profesionales` table with `nombre VARCHAR(200) NOT NULL`, `matricula VARCHAR(50) NOT NULL UNIQUE`, `especialidad VARCHAR(120) NULL`, `slot_default_min INTEGER NOT NULL DEFAULT 30 CHECK (slot_default_min > 0)`, plus `AuditMixin`. The domain flag `activo` (RN-TU-02: only active professionals receive appointments) SHALL map to `AuditMixin.is_active` with no duplicated column, with a partial index `WHERE is_active = true` and an index on `especialidad`.

#### Scenario: Solo profesionales activos reciben turnos
- **WHEN** availability or booking queries filter professionals
- **THEN** only rows with `is_active = true` are eligible, supported by the partial index

#### Scenario: Matricula unica
- **WHEN** a second `Profesional` is inserted with a duplicated `matricula`
- **THEN** the database rejects the row with a uniqueness violation

### Requirement: Paciente
The system SHALL provide a `pacientes` table with `nombre VARCHAR(200) NOT NULL`, `telefono VARCHAR(16) NOT NULL CHECK (telefono ~ '^\+[1-9][0-9]{7,14}$')` (E.164) and `dni VARCHAR(16) NULL`, plus `AuditMixin`. There SHALL be a non-unique btree index on `pacientes(telefono)`; there SHALL NOT be a UNIQUE constraint on phone numbers in v1 (deduplication deferred to C-05/C-11). E.164 validation SHALL also exist in the app layer (strict Pydantic) in addition to the DB CHECK (defense in depth).

#### Scenario: Telefono no-E.164 es rechazado en dos capas
- **WHEN** a `Paciente` is created with a phone outside E.164 format
- **THEN** the app rejects it with a typed validation error and the DB CHECK rejects it as well

#### Scenario: Telefono repetido permitido con indice
- **WHEN** two patients share the same phone number
- **THEN** both rows persist and phone lookup uses the btree index

### Requirement: Tratamiento
The system SHALL provide a `tratamientos` table with `nombre VARCHAR(120) NOT NULL UNIQUE`, `duracion_min INTEGER NOT NULL CHECK (duracion_min > 0)`, plus `AuditMixin`, where `is_active` is the catalog `activo` flag (no duplicated column), with a partial index `WHERE is_active = true`.

#### Scenario: Nombre unico y duracion positiva
- **WHEN** a `Tratamiento` is inserted with a duplicated `nombre` or with `duracion_min <= 0`
- **THEN** the database rejects the row (UniqueViolation / CheckViolation) and the app validates beforehand with a typed error

#### Scenario: Catalogo activo filtra por is_active
- **WHEN** treatment catalog listings are queried
- **THEN** only rows with `is_active = true` are returned, supported by the partial index

### Requirement: Persistencia e infra
The system SHALL provide a synchronous `BaseRepository[T]` (`get`, paginated `list` excluding inactive by default, `add`, `soft_delete`) with strict return types, and a `UnitOfWork` with context manager (`commit`/`rollback`) over the `Session` from `core/db.py`. It SHALL use `def`, never `async def` (no non-blocking I/O; async hard rule). Migration `backend/alembic/versions/001_core_tables.py` (convention `NNN_*`, `down_revision=None`) SHALL create the enum plus the 4 tables with checks and indexes, handwritten as a reviewable diff, with a `downgrade()` that reverts everything in reverse order.

#### Scenario: Migracion 001 up-down-up
- **WHEN** `alembic upgrade head` runs on an empty database, then `downgrade`, then `upgrade` again
- **THEN** it exits 0 in all three runs, creating the enum, the 4 tables, checks and indexes, and fully reverting on downgrade

#### Scenario: Repositorio y UnitOfWork sincronicos
- **WHEN** persistence operations run through `BaseRepository` inside a `UnitOfWork`
- **THEN** `commit` persists and failures `rollback`, with all code paths using plain `def`

### Requirement: Seed minimo idempotente
The system SHALL provide an idempotent seed CLI (`run_seed`, never auto-run on import/startup) with get-or-create by natural keys (`users.email`, `profesionales.matricula`, `tratamientos.nombre`): 1 synthetic secretaria, 1 fictitious example professional, 3 treatments (limpieza 30, consulta 20, conducto 60). It SHALL read `CANCEL_MIN_HOURS` from settings (SU-01, never hardcoded) and SHALL use only synthetic data (fictitious-range phones, `example.test` domain). The seed SHALL hash with bcrypt (new dependency) via a minimal `hash_password()` in `core/security.py`; verify/login remain in C-03.

#### Scenario: Seed idempotente
- **WHEN** the seed runs twice in a row against the same DB
- **THEN** the counts of `users`, `profesionales` and `tratamientos` are identical after both runs with no duplicates by natural key

#### Scenario: Constraints rechazan datos invalidos
- **WHEN** a duplicated matricula, a non-E.164 phone or `duracion_min <= 0` is inserted
- **THEN** the DB rejects the row (UniqueViolation / CheckViolation) and the app layer validates beforehand with a typed error
