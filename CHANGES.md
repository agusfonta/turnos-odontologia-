# CHANGES — Secuencia de Implementación

> Índice canónico de todos los changes del proyecto **turnos-odontologia** (single-clínica, FastAPI + React).
> Cada change es atómico: un agente puede implementarlo en una sesión (~4-6 horas).
> **Leer este archivo antes de ejecutar cualquier `/opsx:propose`.**

---

## Cómo usar este documento

1. Identificar el change a implementar (verificar que sus dependencias están en `openspec/changes/archive/`).
2. Leer los docs de la knowledge-base indicados en "Leer antes".
3. Ejecutar `/opsx:propose <nombre-del-change>`.
4. Al terminar el change, archivarlo con `/opsx:archive <nombre-del-change>`.
5. Marcar el checkbox `[x]` en este archivo.

---

## Árbol de dependencias

```
C-01 foundation-setup
  └── C-02 modelos-core-y-seed
        └── C-03 auth-jwt-rbac                    ← desbloquea TODO lo demás
              └── C-04 disponibilidad-y-reserva   ← corazón del MVP
                    │
                    ├── C-05 gestion-secretaria-turnos   [Backend Core]
                    │     │
                    │     └── C-10 agenda-interna-spa ──┐  (+ C-06)
                    │                                   │
                    ├── C-06 bloqueos-y-agenda ─────────┘  [Backend Aux]
                    │
                    ├── C-07 autogestion-por-token
                    │     └── C-09 portal-reserva-publica ─┐  (+ C-04)
                    │                                      │
                    └── C-08 recordatorios-whatsapp ───────┤  [Backend Aux]
                                                          │
                                                          ▼
                                              C-11 hardening-deploy
```

### Paralelismo por fase

> Cada "gate" es un punto de sincronización. Los changes dentro de un grupo pueden ejecutarse en paralelo.

```
GATE 0: ninguna
  → C-01 (solo)

GATE 1: C-01 ✓
  → C-02 (solo)

GATE 2: C-02 ✓
  → C-03 (solo)

GATE 3: C-03 ✓
  → C-04 (solo — todo el dominio cuelga de turnos)

GATE 4: C-04 ✓                     ← PRIMER FORK (4 paralelos)
  → C-05 gestion-secretaria-turnos  [Agente A]
  → C-06 bloqueos-y-agenda          [Agente B]
  → C-07 autogestion-por-token      [Agente A — si C-05 ✓]
  → C-08 recordatorios-whatsapp     [Agente B — si C-06 ✓]

GATE 5: C-05 + C-06 + C-07 ✓        ← FORK frontend (2 paralelos)
  → C-09 portal-reserva-publica     [Agente C]
  → C-10 agenda-interna-spa         [Agente B — ayuda en frontend]

GATE 6: C-08 + C-09 + C-10 ✓
  → C-11 hardening-deploy           [Agente A]
```

### Camino crítico (7 changes — mínimo irreducible)

```
C-01 → C-02 → C-03 → C-04 → C-05 → C-10 → C-11
```

> Rama alternativa de igual longitud: `C-04 → C-07 → C-09 → C-11` (portal público en vez de agenda interna).

### Plan óptimo con 3 agentes

```
Paso │ Agente A (Backend Core)      │ Agente B (Backend Aux)       │ Agente C (Frontend)
─────┼──────────────────────────────┼──────────────────────────────┼─────────────────────────
  1  │ C-01 foundation-setup        │              —               │         —
  2  │ C-02 modelos-core-y-seed     │              —               │         —
  3  │ C-03 auth-jwt-rbac           │              —               │         —
  4  │ C-04 disponibilidad-y-reserva│              —               │         —
  5  │ C-05 gestion-secretaria      │ C-06 bloqueos-y-agenda       │         —
  6  │ C-07 autogestion-por-token   │ C-08 recordatorios-whatsapp  │         —
  7  │              —               │ C-10 agenda-interna-spa      │ C-09 portal-reserva
  8  │ C-11 hardening-deploy        │              —               │         —
```

---

## FASE 0 — Cimientos

### [C-01] `foundation-setup`
- **Estado**: `[x]` completado (archivado 2026-10-02 → `openspec/changes/archive/2026-10-02-c-01-foundation-setup/`; spec sincronizada en `openspec/specs/foundation/spec.md`)
- **Scope**: Scaffolding completo del monorepo + infraestructura base (DD-02)
  - Estructura `backend/app/{domain,application,infrastructure,api,core}` + `frontend/src/{features,shared,pages}` según `08`
  - `backend/`: FastAPI app mínima con `GET /api/health`, Alembic inicializado, `core/` con settings (zona `America/Argentina/Buenos_Aires`), logger, db, exceptions
  - `frontend/`: Vite + React 18 + TS 5 + Tailwind + Zustand + api client base
  - `docker-compose.yml`: api + web + postgres 15 + redis 7
  - `.env.example` en cada sub-proyecto: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `WA_PROVIDER_API_KEY`, `CLINIC_TIMEZONE`, `CANCEL_MIN_HOURS` (sin defaults sensibles hardcodeados)
  - GitHub Actions CI: jobs paralelos backend (pytest) y frontend (tsc + build)
- **Dependencias**: ninguna
- **Governance**: BAJO
- **Leer antes**:
  - `knowledge-base/01_vision_y_objetivos.md` (qué es el sistema y por qué existe)
  - `knowledge-base/02_descripcion_general.md` §Stack
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-01, §DD-02

---

## FASE 1 — Núcleo y acceso

### [C-02] `modelos-core-y-seed`
- **Estado**: `[x]` completado (archivado 2026-10-02 → `openspec/changes/archive/2026-10-02-c-02-modelos-core-y-seed/`; spec sincronizada en `openspec/specs/core-models/spec.md`)
- **Scope**: Entidades base + migraciones iniciales + seed mínimo (US-002/004/006 dependen de estas tablas)
  - Modelos: `User` (roles secretaria/odontologo), `Profesional` (matrícula única, `activo`, `slot_default_min`), `Paciente` (teléfono E.164, índice teléfono), `Tratamiento` (`duracion_min > 0`, `activo`)
  - `AuditMixin` con `is_active`, `created_at`, `updated_at`, `deleted_at`
  - `BaseRepository[T]`, `UnitOfWork`
  - Migración 001: tablas users, profesionales, pacientes, tratamientos
  - Seed mínimo idempotente: 1 secretaria, 1 profesional ejemplo, 3 tratamientos (limpieza 30m, consulta 20m, conducto 60m), parámetro `CANCEL_MIN_HOURS=24`
  - Tests: constraints (matrícula única, teléfono válido, duración > 0), seed idempotente
- **Dependencias**: C-01
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §Profesional, §Paciente, §Tratamiento, §Seed data inicial
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones aplicados
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-01, §SU-01
  - `knowledge-base/03_actores_y_roles.md` §Actores del sistema

### [C-03] `auth-jwt-rbac`
- **Estado**: `[ ]` pendiente
- **Scope**: Autenticación JWT + RBAC por rol (matriz de 03)
  - `POST /api/auth/login` — JWT access corto + refresh, rate limiting 5/60s por IP+email
  - `POST /api/auth/refresh` — rotación de refresh token, blacklist del anterior
  - `POST /api/auth/logout` — blacklist del access token
  - `GET /api/auth/me` — info del usuario actual
  - `PermissionContext`: `require_role()`, `require_secretaria()`, `require_odontologo()`
  - Campos JWT: `sub`, `roles`, `email`, `jti`, `type`, `iat`, `exp`
  - Refresh token en cookie HttpOnly (secure, samesite=lax)
  - Frontend: página login + guard de rutas + store de sesión (base para C-10)
  - Tests: login correcto, token expirado, rate limit, refresh rotation, matriz RBAC 403
- **Dependencias**: C-02
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/03_actores_y_roles.md` §RBAC — Matriz de permisos
  - `knowledge-base/08_arquitectura_propuesta.md` §Seguridad
  - `knowledge-base/05_reglas_de_negocio.md` §Dominio: Excepciones globales
  - `knowledge-base/02_descripcion_general.md` §Stack tecnológico

---

## FASE 2 — Dominio de turnos (backend)

> Los changes C-05, C-06, C-07 y C-08 pueden proponerse en paralelo una vez archivado C-04. C-09 requiere C-07; C-10 requiere C-05 + C-06.

### [C-04] `disponibilidad-y-reserva`
- **Estado**: `[ ]` pendiente
- **Scope**: Cálculo de huecos + alta de reserva — corazón del MVP (US-001, US-004; Flujo 1)
  - `GET /api/profesionales` — odontólogos activos y especialidades
  - `GET /api/disponibilidad?profesional_id&desde&hasta&tratamiento_id` — huecos calculados con duración del tratamiento o `slot_default_min` (RN-AG-03), excluye turnos ocupados y bloqueos (RN-AG-01, RN-AG-02)
  - `POST /api/turnos` — pública (nombre + teléfono E.164, valida profesional activo y hueco real RN-TU-02) y autenticada (secretaria); crea turno `reservado` + `token_publico` único (RN-TU-03) + auditoría append-only (RN-GL-01); ciclo de estados RN-TU-04
  - Persistencia en timestamptz con zona de la clínica (RN-GL-02)
  - Condición de carrera hueco-ocupado-entre-consulta-y-alta → 409 + huecos actualizados; teléfono inválido → 422; profesional inactivo → 404
  - Migración 002: tablas turno (índices `(profesional_id, inicio)`, `(estado)`, `(paciente_id)`), bloqueo, auditoria_turno
  - Encola job de recordatorio en Redis al crear (el worker lo consume en C-08)
  - Tests: anti-solape concurrente, exclusión de bloqueos, ciclo de estados, 409/422/404
- **Dependencias**: C-03
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §Turno, §Bloqueo, §AuditoriaTurno
  - `knowledge-base/05_reglas_de_negocio.md` §Dominio: Agenda, §Dominio: Turnos
  - `knowledge-base/06_funcionalidades.md` §US-001, §US-004
  - `knowledge-base/07_flujos_principales.md` §Flujo 1: Reserva online

### [C-05] `gestion-secretaria-turnos`
- **Estado**: `[ ]` pendiente
- **Scope**: Alta manual, mover y cancelar por secretaria (US-005 parcial, US-006; Flujo 2)
  - `POST /api/turnos/manual` — alta con paciente nuevo o existente (deduplicación por teléfono según 10: crear si no existe)
  - `PATCH /api/turnos/{id}` — reprogramar: respeta anticipación mínima configurable (RN-TU-01), revalida disponibilidad, reprograma/cancela notificaciones pendientes del turno
  - `DELETE /api/turnos/{id}` — cancelar con anticipación (RN-TU-01)
  - Sobreturno solo con marca explícita + rol secretaria + auditoría (RN-AG-04); solape sin marca → 409; reprogramación fuera de anticipación → 422
  - Toda operación genera `AuditoriaTurno` (RN-GL-01)
  - Tests: sobreturno explícito vs 409, anticipación 422, reprogramación revalida hueco, auditoría por operación
- **Dependencias**: C-04
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-005, §US-006
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-04, §RN-TU-01, §RN-TU-04, §RN-GL-01
  - `knowledge-base/07_flujos_principales.md` §Flujo 2: Gestión de secretaria
  - `knowledge-base/04_modelo_de_datos.md` §Turno, §AuditoriaTurno

### [C-06] `bloqueos-y-agenda`
- **Estado**: `[ ]` pendiente
- **Scope**: Bloqueos de horarios + vistas de agenda interna (US-002, US-003)
  - `POST /api/bloqueos` + `DELETE /api/bloqueos/{id}` — solo secretaria, con motivo; excluyen disponibilidad (RN-AG-02)
  - `GET /api/agenda?profesional_id&dia` — vista día/semana: turnos ordenados con paciente, tratamiento, estado y origen online/secretaria; odontólogo ve solo su agenda (CA US-003)
  - Sin migración nueva (usa tablas de la migración 002)
  - Tests: bloqueo excluye huecos, agenda filtra por profesional y rol, distingue estados/origen
- **Dependencias**: C-04
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-002, §US-003
  - `knowledge-base/04_modelo_de_datos.md` §Bloqueo
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-02
  - `knowledge-base/03_actores_y_roles.md` §RBAC — Matriz de permisos

### [C-07] `autogestion-por-token`
- **Estado**: `[ ]` pendiente
- **Scope**: Gestión pública del turno sin login vía token (US-005; rutas públicas de 03)
  - `GET /api/turnos/por-token/{token}` — detalle mínimo para gestión
  - `POST /api/turnos/por-token/{token}/confirmar` — confirmación sin login (RN-NO-02)
  - `PATCH /api/turnos/por-token/{token}` — reprogramar con anticipación (RN-TU-01) + revalida hueco
  - `DELETE /api/turnos/por-token/{token}` — cancelar con anticipación (RN-TU-01)
  - Token inválido → 404 sin exponer datos; cada operación audita (RN-GL-01)
  - Tests: confirmar/cancelar/reprogramar por token, 404 sin fuga de datos, bloqueo por anticipación, auditoría
- **Dependencias**: C-04
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-005
  - `knowledge-base/03_actores_y_roles.md` §Rutas públicas
  - `knowledge-base/05_reglas_de_negocio.md` §RN-TU-01, §RN-TU-03, §RN-NO-02
  - `knowledge-base/07_flujos_principales.md` §Flujo 1 (paso 7), §Flujo 3 (paso 4)

---

## FASE 3 — Notificaciones

### [C-08] `recordatorios-whatsapp`
- **Estado**: `[ ]` pendiente
- **Scope**: Recordatorio 24hs + confirmación 1-clic por WhatsApp (US-007, DD-04; Flujo 3)
  - `WAClient` en infrastructure (interfaz + mock + proveedor real configurable vía `WA_PROVIDER_API_KEY`; solo envío en v1)
  - Worker Redis: toma notificaciones `pendientes` con `scheduled_at <= now`, envía plantilla con links confirmar/cancelar por token, marca `enviada`/`fallida` con reintento y backoff
  - Fallo de proveedor no altera el turno (RN-NO-01); confirmación 1-clic sin login (RN-NO-02)
  - Migración 003: tabla notificacion (canal, tipo, estado, scheduled_at, sent_at)
  - Tests: agendado 24hs antes, envío y marcado, reintento con backoff, fallo no rompe reserva, confirm 1-clic
- **Dependencias**: C-04
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-007
  - `knowledge-base/07_flujos_principales.md` §Flujo 3: Recordatorio y confirmación WhatsApp
  - `knowledge-base/05_reglas_de_negocio.md` §Dominio: Notificaciones
  - `knowledge-base/04_modelo_de_datos.md` §Notificacion
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-04

---

## FASE 4 — Frontend y producción

> C-09 y C-10 pueden proponerse en paralelo. C-11 requiere C-08 + C-09 + C-10 archivados.

### [C-09] `portal-reserva-publica`
- **Estado**: `[ ]` pendiente
- **Scope**: Portal público mobile-first de reserva y autogestión (Flujo 1 + rutas públicas)
  - `/reservar` — elige profesional + tratamiento + rango de fechas, muestra huecos (`GET /api/disponibilidad`), alta con nombre + teléfono, confirmación con token de gestión
  - `/turnos/:token` — ver, confirmar, cancelar y reprogramar por token (endpoints de C-07)
  - Manejo de errores: 409 muestra huecos actualizados, 422 detalla campo, 404 profesional/token
  - Mobile-first responsive (CA-3 US-001)
  - Tests: flujo e2e reserva → confirmación, gestión por token, estados de error
- **Dependencias**: C-04, C-07
- **Governance**: BAJO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-001, §US-004, §US-005
  - `knowledge-base/07_flujos_principales.md` §Flujo 1: Reserva online
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios (frontend)
  - `knowledge-base/03_actores_y_roles.md` §Rutas públicas

### [C-10] `agenda-interna-spa`
- **Estado**: `[ ]` pendiente
- **Scope**: SPA autenticada de agenda para secretaria y odontólogo (US-002, US-003; Flujo 2)
  - `/agenda` — vista día/semana por profesional (secretaria: multi-odontólogo; odontólogo: solo la propia)
  - Crear turno manual (paciente nuevo/existente), mover (drag&drop o acción explícita con validación anti-solape), cancelar, bloquear horarios (endpoints de C-05 y C-06)
  - Badges de estado (reservado/confirmado/cancelado/ausente/atendido) y origen online/secretaria
  - Manejo de 409 (solape) y 422 (anticipación) con mensajes accionables
  - Tests: vistas por rol (aislamiento de agenda), mover con validación, sobreturno explícito
- **Dependencias**: C-05, C-06
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-002, §US-003, §US-006
  - `knowledge-base/07_flujos_principales.md` §Flujo 2: Gestión de secretaria
  - `knowledge-base/03_actores_y_roles.md` §RBAC — Matriz de permisos
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios (frontend)

### [C-11] `hardening-deploy`
- **Estado**: `[ ]` pendiente
- **Scope**: Endurecimiento transversal y deploy single-clínica a producción
  - Validación global: teléfono E.164, timestamptz + `CLINIC_TIMEZONE`, schemas estrictos en todos los routers
  - Rate limiting en rutas públicas (reserva, disponibilidad, por-token)
  - Logging estructurado + health checks + observabilidad mínima (latencia disponibilidad, jobs WA)
  - `docker-compose.prod.yml` + guía de deploy single-clínica (DD-01) + checklist de métricas de éxito (cero dobles reservas, ausentismo, tiempo secretaria, % online)
  - Preguntas abiertas resueltas o parametrizadas: anticipación (SU-01), deduplicación pacientes, proveedor WA (ver 10)
  - Tests: carga sobre disponibilidad, smoke e2e post-deploy
- **Dependencias**: C-08, C-09, C-10
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/01_vision_y_objetivos.md` §Alcance v1.0, §Fuera de alcance, §Métricas de éxito
  - `knowledge-base/10_preguntas_abiertas.md` (todas — resolver o parametrizar)
  - `knowledge-base/08_arquitectura_propuesta.md` §Seguridad, §Variables de entorno
  - `knowledge-base/09_decisiones_y_supuestos.md` §Supuestos inferidos
