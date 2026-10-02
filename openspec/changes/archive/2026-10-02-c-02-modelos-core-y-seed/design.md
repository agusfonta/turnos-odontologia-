# Design: c-02-modelos-core-y-seed

## Context
C-01 dejó el esqueleto verificado: `backend/app/{domain,application,infrastructure,api,core}` con `main.py` (prefijo `/api`), `core/settings.py` (6 vars, `CANCEL_MIN_HOURS=24` default), `core/db.py` (`Base: DeclarativeBase`, `SessionLocal`, `get_db` sincrónica), `alembic/env.py` leyendo `DATABASE_URL` con `versions/` vacío, y tests smoke en verde. KB 04 fija atributos/constraints/índices por entidad; KB 08 fija capas `domain/application/infrastructure` y jobs Redis (estos últimos llegan en C-08); DD-01 exige capas que permitan evolucionar a multi-tenant; DD-03 fija reserva sin login. Se diseña solo persistencia base + seed: sin HTTP, sin auth funcional, sin Turno.

## Decisions
1. **`User` staff-only (`secretaria`/`odontologo`, enum Postgres `user_role`)** — por qué: DD-03 + matriz 03 (paciente opera sin login). Alternativa (rol `paciente` en users): descartada, crearía cuentas inútiles y contradice Flujo 1. Trade-off: si un día hay login paciente, será migración + C-03 dedicado.
2. **`activo` de Profesional/Tratamiento ≡ `AuditMixin.is_active` (alias de dominio, cero columnas duplicadas)** — por qué: CHANGES.md pide ambos nombres para el mismo concepto (RN-TU-02 "profesional activo"); duplicar booleanos diverge. Se implementa como `property`/sinónimo documentado, con índice parcial `WHERE is_active`.
3. **Teléfono E.164 con doble validación (Pydantic + `CHECK` regex `^\+[1-9][0-9]{7,14}$`) e índice NO único** — por qué: regla dura de validación estricta + invariante en DB (skill postgres); sin unique por decisión de diferir dedup (DD-03 la acepta). Alternativa (unique desde día 1): descartada, bloquearía reservas legítimas (teléfono familiar compartido) antes de definir la regla en C-05.
4. **`Tratamiento.id` entero identity; resto UUID con default app-side (`uuid4`)** — por qué: fiel a KB 04 (`Tratamiento.id` sin uuid) y evita `pgcrypto`/superusuario en 001. Trade-off: dos estrategias de PK; documentado en el spec, sin impacto porque las FKs llegan en C-04.
5. **Email unique case-sensitive + normalización a minúsculas en app (sin CITEXT)** — por qué: evita la extensión en 001; la unicidad real la garantiza el normalizador validado por test. Riesgo cubierto por test de doble alta con distinto case.
6. **`BaseRepository[T]` + `UnitOfWork` sincrónicos en `infrastructure/`** — por qué: `get_db` es sincrónica y no hay I/O async (regla dura async; skill fastapi: `def` por defecto). Alternativa (repos async con `async_session`): descartada, todo el stack sync de C-01 se volvería async sin beneficio.
7. **Migración `001_core_tables.py` escrita a mano (no autogenerate), con `downgrade()` completo** — por qué: skill postgres exige migraciones declarativas como diff revisable; autogenerate mete ruido (órdenes de índice, tipos de enum). `down_revision=None` porque `versions/` está vacío (verificado).
8. **Seed CLI explícito (`run_seed(session)`, `python -m app.infrastructure.seed`), NUNCA auto-run en startup/import** — por qué: efectos laterales en import rompen tests y deploys; idempotencia por get-or-create sobre claves naturales. `CANCEL_MIN_HOURS` se lee de settings y se loguea/valida (`>= 0`), nunca hardcode (SU-01).
9. **bcrypt mínimo en C-02 (`core/security.hash_password`, sin verify)** — por qué: el seed debe dejar una secretaria con hash real para que C-03 implemente login sin re-seed; meter solo hash acota la superficie (verify/RBAC son C-03). Alternativa (hash placeholder): descartada, dejaría la cuenta inservible y un test de C-03 dependería de re-seed manual.
10. **Tests de constraints contra Postgres real (compose/CI service), con `pytest.skip` si no hay DB** — por qué: `CHECK` regex y violaciones de unicidad tienen semántica distinta en SQLite; validar contra SQLite daría falsa confianza (skill postgres: tipos/constraints correctos desde el inicio). Los tests puros (validadores Pydantic, normalización) corren sin DB. CI backend suma `services: postgres:15-alpine`.

## Cumplimiento de reglas duras (8/8 por diseño)
| # | Regla | Cómo se cumple en C-02 |
|---|---|---|
| 1 | Pydantic estricto + response_model/tipo siempre | Validadores estrictos (E.164, email lower, `duracion_min>0`); repos y `run_seed` con tipos de retorno; sin campos fantasma (schemas espejan columnas) |
| 2 | async correcto | Todo `def` (modelos, repos, UoW, seed); prohibido `async def` en este change |
| 3 | Anti-solape en DB, no solo app | N/A sin `turno` (hook dejado: PG15 + Alembic; exclusion constraint llega en C-04/002). Invariantes de C-02 (unique, checks) SÍ van en DB, no solo app |
| 4 | TS estricto, no any | N/A (sin frontend en C-02) |
| 5 | No commit/push sin pedido | Ningún step commitea; CI solo verifica |
| 6 | Modelo solo con migración versionada | `001_core_tables.py` numerada, a mano, con downgrade; cero `Base.metadata.create_all` en código |
| 7 | WA nunca en request, siempre job | N/A (sin WA en C-02; `WA_PROVIDER_API_KEY` sigue placeholder) |
| 8 | Datos sintéticos, nunca reales | Seed y fixtures solo `example.test` + teléfonos ficticios; test que aserta ausencia de datos reales |

## Risks
- **Divergencia case del email** → mitigado por normalizador + test de doble alta con distinto case.
- **Regex E.164 en PG vs Pydantic** → misma constante documentada en un solo módulo; test parametrizado con casos válidos/inválidos en ambas capas.
- **bcrypt pin vs C-03** → se fija `bcrypt>=4.1` en requirements; C-03 reutiliza `core/security.py` (no introduce segunda lib).
- **Tests que requieren PG sin Docker local** → skip explícito + CI con servicio PG; documentado en tasks (no silently green).
- **Tentación de meter `turno` "de paso"** → prohibido en tasks; C-04 lo trae con su exclusion constraint.

## Project Standards (auto-resolved desde `.atl/skill-registry.md`)
- `fastapi`: `def` por defecto; tipos de retorno/`response_model` siempre; sin `...` defaults; entrypoint ya declarado en `pyproject`.
- `supabase-postgres-best-practices`: constraints que hacen cumplir invariantes (unique matrícula/email/nombre-tratamiento, checks `>0` y E.164), índices de soporte (incl. parciales `WHERE is_active`), tipos correctos desde el inicio (`timestamptz`, `Uuid`), migraciones declarativas revisables, transacciones cortas en UoW.
- `test-driven-development`: IRON LAW (código borrado si precede al test) → RED un comportamiento por test → GREEN mínimo → TRIANGULATE (≥2 casos) → REFACTOR solo en verde + suite completa.
