# Skill Registry

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

## User Skills

| Trigger | Skill | Path |
|---------|-------|------|
| Writing, reviewing, or refactoring React/Next.js code; React components, Next.js pages, data fetching, bundle optimization, performance improvements | vercel-react-best-practices | .agents/skills/vercel-react-best-practices/SKILL.md |
| Building new UI or reshaping an existing one; aesthetic direction, typography, non-templated visual design | frontend-design | .agents/skills/frontend-design/SKILL.md |
| "review my UI", "check accessibility", "audit design", "review UX", "check my site against best practices" | web-design-guidelines | .agents/skills/web-design-guidelines/SKILL.md |
| Working with shadcn/ui, component registries, presets, --preset codes, projects with components.json; "shadcn init" | shadcn | .agents/skills/shadcn/SKILL.md |
| Working with FastAPI APIs, Pydantic models, dependencies, streaming/SSE, serving frontend apps | fastapi | .agents/skills/fastapi/SKILL.md |
| Creating/altering Postgres tables, schema design, migrations, RLS policies, indexes, triggers, functions, pg_cron/pgmq, pgvector, slow queries, connection exhaustion, locking | supabase-postgres-best-practices | .agents/skills/supabase-postgres-best-practices/SKILL.md |
| Implementing any feature or bugfix, before writing implementation code | test-driven-development | .agents/skills/test-driven-development/SKILL.md |
| Verifying frontend functionality, debugging UI behavior, browser screenshots, browser logs on local web apps | webapp-testing | .agents/skills/webapp-testing/SKILL.md |
| docker compose, compose file, multi-container orchestration, Postgres+Redis+API+Vite via compose.yml | docker-skills (compose) | .agents/skills/docker-compose/SKILL.md |
| Escribir/modificar casos de uso que persisten datos, UnitOfWork, commit/rollback, efectos post-commit (Redis/WhatsApp), IntegrityError/409 por solape, tests de atomicidad | uow-transacciones | .agents/skills/uow-transacciones/SKILL.md |
| Alta manual, reprogramar, cancelar o confirmar turnos; puertas secretaria (JWT) y token publico; C-05 / C-07 | turno-use-case | .agents/skills/turno-use-case/SKILL.md |

> Source: vendored in `.agents/skills/` (11 skills; `uow-transacciones` y `turno-use-case` son project-authored, sin origen externo). Origin refs (state.skills.installed): vercel-labs/agent-skills@vercel-react-best-practices, anthropics/skills@frontend-design, vercel-labs/agent-skills@web-design-guidelines, shadcn/ui@shadcn, fastapi/fastapi@fastapi, supabase/agent-skills@supabase-postgres-best-practices, obra/superpowers@test-driven-development, anthropics/skills@webapp-testing, full-stack-skills/docker-skills (vendored as `docker-compose/`). SDD workflow skills (openspec-*, active-orchestrator, kb-creator, etc.) intentionally skipped.

## Compact Rules

Pre-digested rules per skill. Delegators copy matching blocks into sub-agent prompts as `## Project Standards (auto-resolved)`.

### vercel-react-best-practices
- Eliminate waterfalls: parallelize independent fetches with Promise.all, start promises early / await late, defer await into branches
- Bundle: import directly (no barrel files), prefer statically analyzable paths, next/dynamic for heavy components, defer third-party scripts
- Client fetching: use SWR for dedup; dedupe global event listeners; use passive listeners for scroll; version localStorage schema
- Re-render: don't subscribe to state only used in callbacks; derive state during render (not effects); functional setState; split independent hooks
- Rendering: hoist static JSX, content-visibility for long lists, ternary not && for conditionals, useTransition/useDeferredValue for non-urgent work
- JS: early exit, Map/Set for lookups, combine filter/map passes, hoist RegExp out of loops, defer non-critical work to requestIdleCallback
- Rule files live in rules/ (e.g. rules/async-parallel.md); full guide in AGENTS.md

### frontend-design
- Ground design in subject matter: propose concrete subject + audience + job before designing; use brief's real content
- Hero first: open with the most characteristic thing (headline/image/demo), not default big-number + gradient accent
- Typography: 1-2 deliberate families with clear scale; line length <80 chars; never single-word accent color, all-caps labels, or gratuitous eyebrows
- Structure encodes info: no numbered 01/02/03 unless content is a real sequence; no SaaS-card-kit (identical rounded cards + soft shadow everywhere)
- One orchestrated motion moment max; interaction-driven motion OK; respect reduced motion, keyboard focus, mobile responsive
- Two passes: plan tokens (color 4-6 hex, type roles, layout+ASCII wireframe, principles) → review against brief for genericness → then code
- Copy: user vocabulary, active voice, CTA names the outcome ("Save changes"); errors explain fix, empty states invite action

### web-design-guidelines
- Always fetch fresh guidelines first via WebFetch: https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
- Review the user-specified file or pattern (ask which files if not given); never review from memory of old rules
- Apply ALL fetched rules; output findings only in the terse `file:line` format defined by the guidelines
- No implementation in review mode — report findings, don't rewrite code

### shadcn
- Existing components first: `npx shadcn@latest search` before custom UI; compose (Tabs+Card+form) with built-in variants and semantic colors (bg-primary), never raw colors
- Styling: className for layout only; flex+gap-* (never space-x/y-*); size-* for square; truncate shorthand; cn() for conditionals; no manual dark: overrides or z-index on overlays
- Forms: FieldGroup+Field (never raw div layout); InputGroupInput/Textarea inside InputGroup; ToggleGroup for 2-7 options; FieldSet+FieldLegend for groups; data-invalid on Field + aria-invalid on control
- Composition: items inside Groups (SelectItem→SelectGroup); Dialog/Sheet/Drawer always need Title (sr-only OK); full Card composition; TabsTrigger inside TabsList; Avatar needs Fallback; Button loading = Spinner+disabled (no isPending)
- Icons: data-icon="inline-start|inline-end", no sizing classes inside components, pass icon objects not string keys
- CLI via project package runner (npx/pnpm dlx/bunx): docs+fetch URLs before using a component; add with --dry-run/--diff preview; never --overwrite without approval; never guess registry — ask

### fastapi
- Run with `fastapi dev` (localhost+reload) / `fastapi run` (prod); declare entrypoint in pyproject [tool.fastapi]; serve built SPA via app.frontend("/", directory="dist") not manual StaticFiles
- Always Annotated style: `Annotated[int, Path/Query(...)]` and `CurrentUserDep = Annotated[dict, Depends(get_current_user)]`; router-level prefix/tags/shared deps on APIRouter, not include_router
- Return type or response_model for validation/filtering/Rust-side serialization; never ORJSONResponse/UJSONResponse (deprecated); never `...` defaults; never Pydantic RootModel (use Annotated[list[int], Field, Body()])
- def by default (threadpool); async only when inner calls are truly non-blocking; never block inside async; mix via Asyncer
- One HTTP operation per function; SSE via response_class=EventSourceResponse + yield ServerSentEvent; tooling: uv, Ruff, ty, SQLModel over SQLAlchemy, HTTPX over Requests

### supabase-postgres-best-practices
- Load this skill BEFORE any DB change, even one column or one query; rule details live in references/ (query-*, conn-*, security-*, schema-*, lock-*, data-*, monitor-*, advanced-*)
- Query: ensure supporting indexes (prefer partial indexes where selective); check EXPLAIN before/after; avoid N+1 and SELECT *
- Connections: pool (transaction mode where appropriate); never per-request new connections; watch for exhaustion/timeouts
- Security: RLS on tenant tables + tests verifying rows invisible to wrong user/tenant; least-privilege roles
- Schema: right column types from the start; constraints enforce invariants (e.g. exclusion constraint for no-overlap per odontólogo); declarative migrations, reviewable diffs
- Concurrency: short transactions, correct isolation, avoid long locks; use queues (pgmq) / scheduled jobs (pg_cron) instead of app polling

### test-driven-development
- IRON LAW: no production code without a failing test first; code written before test → delete it, start over (no "reference", no adapting)
- RED: one behavior per test, clear behavior name, real code (mocks only if unavoidable); run and confirm it FAILS for the expected reason (feature missing, not typo)
- GREEN: minimal code to pass, nothing more (no YAGNI features); run and confirm pass + full project suite still green (bare pytest/npm test/cargo test), output pristine
- REFACTOR only on green: remove duplication, improve names, extract helpers; re-run after each step, stay green, add no behavior
- Bug fix = failing reproduction test first, then cycle; hard-to-test = simplify design; suite red you ignore = report falsified by omission

### webapp-testing
- Python Playwright only: sync_playwright(), headless Chromium, browser.close() always; descriptive selectors (role=/text=/CSS/ID)
- Scripts in scripts/ are black boxes: run `python scripts/with_server.py --help` first, never read source unless --help insufficient
- Single server: `python scripts/with_server.py --server "npm run dev" --port 5173 -- python your_automation.py`; multi (backend+frontend): repeat --server/--port flags
- Automation script contains only Playwright logic (servers pre-managed); always page.wait_for_load_state('networkidle') before DOM inspect/screenshot; reconnaissance-then-action (screenshot/DOM → selectors → act)

### docker-skills
- Compose file: services/networks/volumes(/secrets/configs) top level; service = image or build + ports + environment/env_file + volumes + healthcheck + restart: unless-stopped + depends_on
- Ordering: depends_on with condition: service_healthy (bare depends_on only waits for START); every depended-on service needs a healthcheck (e.g. pg_isready for postgres:16-alpine)
- Networking: default network reaches peers by service name; backend-only data stores get internal: true network; no ports: for internal-only services
- Env: .env auto-loaded for ${VAR} substitution; env_file for per-env bulk vars; never commit .env with secrets (gitignore + .env.example placeholders)
- Multi-env: compose.yml base + compose.override.yml (auto local) / compose.prod.yml (-f explicit); validate with `docker compose config`; modern CLI is `docker compose` (space), not docker-compose
- Single-container → docker-run skill; Dockerfile authoring → docker-dockerfile; multi-host/scaling → Swarm/K8s (kompose convert), not Compose

### uow-transacciones
- Casos de uso reciben `uow_factory: UowFactory` (dep `get_uow_factory`) y abren `with uow_factory() as session:`; nunca una Session de `get_db` para escribir
- NUNCA `commit`/`rollback` en application/ ni api/ (guarda AST en tests/test_transacciones_arquitectura.py); solo el `with` cierra (commit limpio, rollback en excepcion)
- `flush()` final dentro del `with`; devolver DTO frozen dataclass armado adentro, jamas entidades ORM
- Efectos externos (Redis, WhatsApp) solo en router/orquestador DESPUES del retorno; fallo de encolado nunca falla el request
- Alta de turno: TurnoRepository.insertar_si_no_solapa (INSERT ON CONFLICT ON CONSTRAINT ex_turnos_sin_solape DO NOTHING; None => 409; evita deadlock 40P01). UPDATE/reprogramar: sin ON CONFLICT -> advisory lock por profesional (o 40P01 => 409) + 23P01 => 409; otro sqlstate se re-lanza (500). ex_turnos_sin_solape no es diferible
- Ocupacion de aplicacion = excepcion interna (`_HuecoOcupado`) convertida FUERA del `with`; huecos del 409 se releen en UoW NUEVA, nunca con la sesion fallida
- Todo `def`; helpers de modulo llamados por nombre (monkeypatch-ables)
- Tests: `factoria_espia` (orden enter/commit/rollback/close), sin filas tras fallo leido desde OTRA sesion, commit->encolado, Barrier si toca agenda
- Tocar el UoW o el contrato de `reservar_turno` = CRITICO/HIGH: pedir aprobacion antes de escribir

### turno-use-case
- Una funcion por operacion en application/ (alta_manual/reprogramar/cancelar/confirmar_turno); routers finos: actor -> caso de uso -> efectos post-commit -> DTO a response_model
- Dos puertas (secretaria JWT, token publico) al MISMO caso de uso con actor explicito (`AuditoriaActor`); token invalido = mismo 404 que turno inexistente, sin fuga de datos
- Receta en UN `with`: cargar (404) -> `transicionar` de `turno_estados.py` -> anticipacion con `get_settings().CANCEL_MIN_HOURS` (nunca hardcode) -> revalidar hueco (`es_inicio_valido` + `hay_ocupacion` excluyendo el propio turno) -> timestamptz clinica -> `AuditoriaTurno` -> flush + DTO
- `confirmar`: solo transicion + auditoria (sin anticipacion ni hueco)
- Sobreturno solo secretaria con marca explicita (RN-AG-04); la puerta token no crea
- Errores: solape `HuecoOcupadoError` 409; anticipacion/transicion/inicio 422; inexistente 404; otro sqlstate de IntegrityError 500 (anticipacion/transicion aun sin clase AppError)
- Alta/reprogramar: ver uow-transacciones (insertar_si_no_solapa; advisory lock por profesional en UPDATE); `hay_ocupacion`/`ocupados_en_rango` necesitan `excluir_turno_id` (C-05)
- Reglas decididas: secretaria EXENTA de anticipacion minima (RN-TU-01 solo token/paciente; accion auditada); alta manual reusa Paciente por telefono normalizado (crea solo si no existe); reprogramar `confirmado` vuelve a `reservado` y re-encola recordatorio post-commit
- Redis tras el commit: hoy solo `RecordatorioQueue.encolar` (reprogramar = re-encolar); cancelar (ZREM) falta y debe agregarse con tests
- Tests: feliz + cada error, auditoria en exito/no en fallo (otra sesion), ambas puertas, Barrier si toca agenda, commit->Redis
- No restatar reglas: leer knowledge-base/ y openspec/specs/turnos/spec.md; C-05/C-07 MEDIO, cambiar `reservar_turno` CRITICO

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| CHANGES.md | CHANGES.md | Roadmap operativo: 12 changes C-01…C-11 + C-04b, critical path, dependencias |
| README.md | README.md | Intro del proyecto |
| knowledge-base/ | knowledge-base/ | 10 docs canónicos (visión, actores, datos, reglas, flujos, arquitectura) + README |
| openspec/ | openspec/ | Fuente de verdad de specs por capacidad + changes activos |

No se encontraron AGENTS.md / CLAUDE.md / .cursorrules / GEMINI.md / copilot-instructions.md a nivel proyecto. Stack del proyecto (KB): FastAPI + SQLAlchemy + PostgreSQL + Redis + React + TypeScript + Vite + Docker.
