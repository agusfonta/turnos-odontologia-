# Proposal: c-04-disponibilidad-y-reserva

## Why
Es el corazón del MVP (US-001, US-004; Flujo 1): hoy existen `profesionales`, `pacientes`, `tratamientos` (C-02) y auth/RBAC (C-03), pero no hay forma de ver huecos ni de reservar. Sin `turno`, `bloqueo` y `auditoria_turno` (migración 002) todo el FORK de GATE 4 (C-05, C-06, C-07, C-08) está bloqueado, y la invariante más crítica del dominio — un odontólogo no puede tener dos turnos superpuestos (RN-AG-01) — todavía no existe en la base.

## What Changes (scope CHANGES.md, autoritativo)
- `GET /api/profesionales` (público): odontólogos activos con especialidad.
- `GET /api/tratamientos` (público, solo lectura): tratamientos activos con `id`, `nombre`, `duracion_min` (Flujo 1 paso 1; agregado por decisión del usuario, A6).
- `GET /api/disponibilidad?profesional_id&desde&hasta&tratamiento_id` (público): huecos con duración del tratamiento o `slot_default_min` (RN-AG-03), dentro de las franjas de atención del propio profesional (profesional sin horarios → `200 []`), excluyendo turnos que ocupan agenda y bloqueos activos (RN-AG-01, RN-AG-02).
- `POST /api/turnos`:
  - público (nombre + teléfono E.164) → `origen=online`;
  - autenticado como secretaria (mismo endpoint, `Authorization: Bearer`) → `origen=secretaria`, `created_by` = usuario;
  - valida profesional activo y hueco real (RN-TU-02); crea turno `reservado` + `token_publico` único (RN-TU-03) + registro de auditoría append-only (RN-GL-01).
- Ciclo de estados RN-TU-04 como regla de dominio (`reservado → confirmado → atendido|ausente`, `reservado|confirmado → cancelado`, sin saltos), lista para que C-05/C-07 la usen.
- Persistencia en `timestamptz`; entrada sin zona explícita → 422; salida en zona de la clínica (RN-GL-02).
- Errores: hueco ocupado entre consulta y alta → **409 + huecos actualizados**; teléfono inválido → **422**; profesional inexistente/inactivo → **404**.
- Migración `002`: tablas `turnos` (índices `(profesional_id, inicio)`, `(estado)`, `(paciente_id)`; **exclusion constraint anti-solape** por profesional con `btree_gist`), `bloqueos`, `auditoria_turno` (append-only reforzado en DB), `horario_profesional` (franjas semanales por profesional, varias por día, **sin solape en DB** vía exclusion constraint). Upgrade + downgrade completos.
- Seed de C-02 extendido (idempotente, datos sintéticos): el profesional de ejemplo recibe franjas lunes–viernes 09:00–13:00 y 15:00–19:00.
- Encola job de recordatorio en Redis tras el commit (lo consume el worker de C-08); si Redis falla, el turno igual queda creado.
- Tests: anti-solape concurrente, exclusión de bloqueos, franjas por profesional (múltiples, turno dentro de una franja, sin horarios, solape de franjas rechazado en DB), ciclo de estados, 409/422/404.

## Capabilities

### New Capabilities
- `agenda`: catálogo público de profesionales y tratamientos activos y cálculo de disponibilidad (horarios de atención por profesional, duración por tratamiento/slot, exclusión de turnos y bloqueos). C-06 la extiende con alta/baja de bloqueos, ABM de horarios y vistas de agenda.
- `turnos`: reserva de turnos (pública y de secretaria), invariante anti-solape en DB, token público, ciclo de estados, auditoría append-only y encolado del recordatorio. C-05/C-07/C-08 la extienden.

### Modified Capabilities
- Ninguna (`core-models`, `auth` y `foundation` no cambian de comportamiento; C-04 solo los reutiliza).

## Non-goals
- Alta manual con paciente existente/deduplicación, mover, cancelar, sobreturno explícito (C-05). La columna `sobreturno` se crea en 002 (default `false`) para que C-05 no necesite migración, pero C-04 nunca la setea en `true`.
- Endpoints de bloqueos y vistas de agenda (C-06); C-04 solo crea la tabla y respeta bloqueos existentes.
- Endpoints por token (confirmar/cancelar/reprogramar, C-07); C-04 solo genera y devuelve el token.
- Worker, tabla `notificacion` (migración 003), `WAClient` y envío WhatsApp (C-08).
- Rate limiting / anti-abuso del POST público y CAPTCHA (C-11 hardening).
- ABM de horarios por secretaria (alta/baja/edición de franjas) y endpoint de lectura de horarios: diferidos a C-06 (`bloqueos-y-agenda`); en C-04 las franjas se cargan por seed/migración de datos. Feriados automáticos (se cubren con bloqueos), multi-sillón (SU-03), multi-tenant (DD-01). Frontend (C-09/C-10).

## Assumptions (governance CRÍTICO)

> Supuestos aprobados por el usuario 2026-10-27 (A2–A5, A7 tal como se propusieron; A1 reemplazado por horarios por profesional; A6 resuelto incorporando `GET /api/tratamientos` a C-04).

- **A1 — Horarios por profesional — decisión del usuario 2026-10-27**: la KB no modelaba horarios laborales; se agrega la tabla `horario_profesional` en 002 (franjas semanales `dia_semana` 0=lunes…6=domingo, `hora_inicio`/`hora_fin` en zona de la clínica, varias por día, sin solape garantizado en DB). Sin settings de horario global. Excepciones puntuales (vacaciones, feriados) = bloqueos.
- **A2 — Grilla de huecos** (aprobado 2026-10-27): los inicios posibles caen en una grilla desde la `hora_inicio` de cada franja con paso `slot_default_min` del profesional; cada hueco dura `duracion_min` del tratamiento (o `slot_default_min` si no hay tratamiento) y debe caber completo dentro de una sola franja. Solo huecos futuros. Rango consultable máximo: 31 días.
- **A3 — Paciente en la reserva pública** (aprobado 2026-10-27): cada reserva crea un `Paciente` nuevo con nombre + teléfono (DD-03 acepta duplicación; dedup llega en C-05/C-11).
- **A4 — Token** (aprobado 2026-10-27): se genera `token_publico` para **todo** turno (online y secretaria), porque C-08 arma links confirmar/cancelar con él; aleatorio de 256 bits, guardado en claro con `UNIQUE` (el worker necesita el valor para el link; hashearlo lo impediría).
- **A5 — Recordatorio** (aprobado 2026-10-27): se encola al crear (`reservado`), según CHANGES.md, aunque RN-NO-01 dice "turno confirmado"; la política de envío/omisión (p.ej. turnos a menos de 24 h o cancelados) la resuelve el worker de C-08.
- **A6 — `GET /api/tratamientos`** (resuelto 2026-10-27): Flujo 1 paso 1 lo necesita; el usuario decidió incluirlo en C-04 (público, solo lectura, solo activos).
- **A7 — `btree_gist`** (aprobado 2026-10-27): es extensión *trusted* en PG ≥ 13 → la crea un usuario con privilegio `CREATE` sobre la DB, sin superusuario. Si el rol de deploy no lo tiene, el DBA debe crearla antes de `alembic upgrade`.
- Preguntas Altas de 10: login paciente → resuelta por DD-03; anticipación mínima → no aplica a C-04 (aplica a mover/cancelar, C-05/C-07); proveedor WA → no aplica (C-08).

## Success criteria
- `alembic upgrade head` crea `turnos`, `bloqueos`, `auditoria_turno`, `horario_profesional` con constraints/índices/trigger; `downgrade -1` vuelve exactamente al estado de 001; `upgrade` de nuevo funciona.
- Dos reservas concurrentes al mismo hueco → exactamente una 201 y una 409 con huecos actualizados; un INSERT directo solapado es rechazado por la DB (exclusion violation).
- `GET /api/tratamientos` devuelve solo tratamientos activos con `id`, `nombre`, `duracion_min`.
- Disponibilidad solo ofrece huecos dentro de franjas activas del profesional; sin horarios → `200 []`; POST fuera de franja → 422; franjas solapadas del mismo profesional/día rechazadas por la DB.
- Seed corrido 2 veces deja las mismas franjas (sin duplicados).
- Disponibilidad nunca ofrece huecos que pisen turnos activos o bloqueos activos.
- Teléfono inválido → 422; profesional inactivo/inexistente → 404; transiciones de estado inválidas → error de dominio.
- Caída de Redis al encolar → igual 201 y turno persistido, con log de advertencia.
- `pytest` completo en verde (tests de DB contra Postgres real o skip explícito, nunca verde silencioso).

## Impact
- **Backend**: `domain/` (estados, cálculo de huecos puro), `application/` (casos de uso disponibilidad/reserva), `infrastructure/` (modelos, repos, encolador Redis), `api/` (routers `profesionales`, `tratamientos`, `disponibilidad`, `turnos` + schemas), `infrastructure/seed.py` (franjas del profesional de ejemplo), `core/exceptions.py` (409/404 de dominio).
- **DB**: migración `002` (extensión `btree_gist`, tipo de rango `timerange`, 4 tablas, 2 exclusion constraints, trigger append-only).
- **Redis**: nueva key de jobs de recordatorio (contrato para C-08).
- **Dependencias**: posible `tzdata` para `zoneinfo` portable (Windows/CI).
