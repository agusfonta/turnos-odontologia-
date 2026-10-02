# Tasks: c-02-modelos-core-y-seed

> Orden secuencial (un solo agente, GATE 1, governance CRÍTICO). Cada checkbox es verificable. Cargar skills indicadas antes de codificar. TDD obligatorio: ningún código de producción sin test rojo previo.

- [x] **T1 — `AuditMixin` + base + convenciones (skills: `supabase-postgres-best-practices`, `test-driven-development`)**
  - RED: `backend/tests/test_audit_mixin.py::test_soft_delete_marca_is_active_y_deleted_at` + `::test_list_excluye_inactivos_por_defecto` — deben FALLAR (no existe el mixin).
  - GREEN: `AuditMixin` (`is_active`, `created_at/updated_at` timestamptz con `server_default=now()`, `deleted_at` nullable) sobre `Base` existente de `core/db.py`; prohibido `create_all` en código.
  - TRIANGULATE: `test_updated_at_cambia_en_update` + `test_created_at_tiene_default_en_db`.
  - Verificación: `pytest tests/test_audit_mixin.py` verde.

- [x] **T2 — Modelos `User`/`Profesional`/`Paciente`/`Tratamiento` + constraints e índices (skills: `supabase-postgres-best-practices`, `test-driven-development`)**
  - RED: `test_core_models.py::test_matricula_duplicada_rechazada` + `::test_telefono_no_e164_rechazado` + `::test_duracion_min_lte_cero_rechazada` — deben FALLAR.
  - GREEN: `domain/` o `infrastructure/models.py` con las 4 tablas según spec (`users` enum `user_role` sin `paciente`, `activo≡is_active` sin columna duplicada, CHECK E.164 + índice no-único en teléfono, `CHECK (duracion_min>0)`, email normalizado a minúsculas, UUID app-side, identity en tratamientos).
  - TRIANGULATE: `test_email_case_insensitive_unico` + `test_slot_default_min_lte_cero_rechazado` + `test_validador_pydantic_e164parametrizado` (≥5 casos válidos/inválidos) + `test_user_rol_paciente_rechazado`.
  - Verificación: tests de constraint contra Postgres (skip explícito si no hay DB); validadores puros sin DB.

- [x] **T3 — `BaseRepository[T]` + `UnitOfWork` sincrónicos (skills: `test-driven-development`)**
  - RED: `test_repositories.py::test_add_y_get_roundtrip` + `::test_uow_rollback_no_persiste` — deben FALLAR.
  - GREEN: `infrastructure/repositories.py` (`get/list/add/soft_delete`, `list` excluye inactivos por defecto) + `infrastructure/unit_of_work.py` (context manager commit/rollback sobre `SessionLocal`/`get_db`); todo `def`, tipos estrictos.
  - TRIANGULATE: `test_soft_delete_excluye_de_list_e_incluye_con_flag` + `test_list_paginado_limit_offset`.
  - Verificación: `pytest tests/test_repositories.py` verde (usa PG si hay, si no SQLite para esta capa + nota).

- [x] **T4 — Migración `001_core_tables.py` (skills: `supabase-postgres-best-practices`, `test-driven-development`)**
  - RED: `alembic upgrade head` en PG efímero NO crea tablas (estado actual: vacío) — registrar como baseline.
  - GREEN: migración escrita a mano (`down_revision=None`, enum + 4 tablas + checks + índices + parciales `WHERE is_active`) con `downgrade()` inverso completo.
  - TRIANGULATE: `upgrade head` → 4 tablas existen; `downgrade -1` → 0 tablas; `upgrade` de nuevo → 4 tablas (verificar con inspección, sin `create_all`).
  - Verificación: ciclo up/down/up en PG local exit 0; `alembic history` muestra `001` como única revisión.

- [x] **T5 — Seed idempotente + `core/security.hash_password` (skills: `test-driven-development`)**
  - RED: `test_seed.py::test_seed_doble_corrida_mismos_conteos` + `::test_seed_respeta_cancel_min_hours_de_settings` — deben FALLAR.
  - GREEN: `bcrypt>=4.1` en `requirements.txt`; `core/security.py` (solo `hash_password`); `infrastructure/seed.py` (`run_seed`, get-or-create por email/matrícula/nombre, datos 100% sintéticos, `CANCEL_MIN_HOURS` desde settings, CLI `python -m`, sin auto-run).
  - TRIANGULATE: `test_seed_no_duplica_por_clave_natural` (pre-insertar secretaria y re-correr) + `test_seed_sin_datos_reales` (aserta dominio `example.test` + rango ficticio).
  - Verificación: correr seed 2× contra PG local → conteos 1/1/3 idénticos.

- [x] **T6 — CI con Postgres + verificación E2E y cierre**
  - Agregar `services: postgres:15-alpine` (+ healthcheck `pg_isready`) al job `backend` de `.github/workflows/ci.yml` con `TEST_DATABASE_URL` apuntando al servicio; los tests sin DB siguen corriendo igual.
  - Verificación final: `pytest` verde completo, ciclo mig newcomers up/down/up, seed 2×, `rg -i "create_all" backend/app backend/alembic` vacío, ningún dato real en repo. Dejar nota lista para `/opsx:archive` + desbloqueo de C-03.

## Criterio de cierre
T1–T6 en verde + `alembic upgrade head` crea exactamente `users, profesionales, pacientes, tratamientos` + seed idempotente verificado + CI con PG. Recién entonces archivar y habilitar C-03.
