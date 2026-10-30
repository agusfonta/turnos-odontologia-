# Design: c-06-bloqueos-y-agenda

> Governance **MEDIO** (lógica de agenda). Motivación: `proposal.md` — Why. Requisitos: `specs/bloqueos/spec.md`, `specs/agenda/spec.md`, `specs/core-models/spec.md`. Patrón base: C-04b/C-05 y las skills `uow-transacciones` / `turno-use-case`. **D2 y D3 (migración 003) requieren aprobación del usuario antes del apply** — ver Open Questions OQ-1 y OQ-2.

## Context

Estado actual verificado en `main` (`d8a54e8`, C-05 archivado):

- Migración 002: tabla `bloqueos(id, profesional_id, desde, hasta, motivo VARCHAR(200) NOT NULL, CHECK hasta > desde, + AuditMixin: is_active, created_at, updated_at, deleted_at)` con índice parcial `ix_bloqueos_profesional_desde_activos WHERE is_active`. **Sin** `created_by`. La exclusión `ex_turnos_sin_solape` es **solo** sobre `turnos`; entre `turnos` y `bloqueos` no hay ninguna garantía en la base.
- `reservas.hay_ocupacion` chequea turnos **y** bloqueos (aplicación). `BloqueoRepository.ocupados_en_rango` ya filtra `is_active`. La disponibilidad ya excluye bloqueos activos (spec `agenda` "Exclusión de bloqueos").
- C-05: `TurnoRepository.bloquear_agenda(profesional_id)` = `pg_advisory_xact_lock(hashtext(:p))` con `str(uuid)`; lo toman `alta_manual_turno` y `reprogramar_turno`. `reservar_turno` (CRÍTICO) **no** lo toma. `reservar_turno` mapea `IntegrityError` `23P01` → 409 `hueco_ocupado`; `gestion_turnos` mapea `DBAPIError` `23P01`/`40P01` → 409.
- `users` (rol `secretaria`|`odontologo`) y `profesionales` **no están vinculados** (ni FK ni columna). El seed crea una secretaria y un profesional, ningún odontólogo.
- `deps.py`: `get_current_user`, `require_secretaria`, `require_odontologo`; no hay dependencia "staff cualquiera".
- Lecturas públicas (`/api/disponibilidad`) usan `get_db` y `def`; escrituras usan `UowFactory`.
- `RangoInvalidoError` (422 `rango_invalido`) y `ProfesionalNoEncontradoError` (404) existen.

## Goals / Non-Goals

**Goals:**
- Alta/baja de bloqueos por secretaria con el patrón UoW + DTO de C-04b/C-05.
- Invariante "ningún turno activo dentro de un bloqueo activo" garantizado **por Postgres**, también bajo concurrencia y para todas las vías de escritura (incluida la reserva pública), sin tocar el código de `reservar_turno`.
- `GET /api/agenda` día/semana con contrato estable para C-10, aislado por rol.

**Non-Goals:**
- SPA de agenda (C-10). Listado/edición (`PATCH`) de bloqueos: v1 = alta + baja (para cambiar un bloqueo: baja + alta).
- ABM de usuarios/odontólogos ni endpoint para vincular usuario↔profesional (vínculo por seed/SQL hasta un change de administración).
- Bloqueos recurrentes (feriados anuales) o para toda la clínica (un bloqueo por profesional).
- Marcar `atendido`/`ausente` (otra US).
- Tabla de auditoría de bloqueos (ver OQ-4).

## Decisions

### D1. Bloqueo sobre turnos activos → 409 con la lista (no se permite convivir)

- La KB no habla de turnos preexistentes, pero RN-AG-02 ("la agenda nunca ofrece huecos falsos por bloqueo") y 04 §Bloqueo ("no genera turnos en el rango") describen un rango donde el profesional **no atiende**: un turno activo adentro es una inconsistencia que alguien tiene que resolver (avisar al paciente, mover).
- Decisión: si el rango pisa turnos `reservado`/`confirmado` del profesional → 409 `bloqueo_con_turnos` con `turnos: [{id, inicio, fin, estado}]` (sin datos de paciente ni token). La SPA (C-10) los muestra; la secretaria reprograma/cancela con C-05 y reintenta.
- `cancelado`/`atendido`/`ausente` no impiden (no ocupan agenda futura). Como `desde >= ahora` (D5), en la práctica solo hay turnos futuros en juego.
- Esto vuelve el invariante **bidireccional** (D2), que es lo que permite garantizarlo en la base.
- Alternativa descartada: permitir y dejar los turnos como están (la secretaria resuelve a mano). Más simple y haría inofensiva la carrera de D2, pero deja turnos vivos en un rango "sin atención" que la agenda pública no ofrece y que nadie está obligado a resolver; los recordatorios (C-08) saldrían igual. Si el usuario prefiere esta opción, D2 se reduce a "turno nuevo dentro de bloqueo" (ver OQ-2).
- Alternativa descartada: cancelar automáticamente los turnos pisados. Efecto masivo e irreversible sin confirmación, y obliga a notificar pacientes (C-08).

### D2. Garantía en la base: triggers con advisory lock por profesional (migración 003) — **requiere aprobación (OQ-1)**

- Problema: una `EXCLUDE` no cruza tablas. Hoy un `POST /api/bloqueos` y un `POST /api/turnos` concurrentes pueden ver ambos "libre" y confirmar los dos. La regla dura "NUNCA validar anti-solape solo en la app" pide una garantía en Postgres.
- Decisión: dos funciones PL/pgSQL `VOLATILE` + triggers `BEFORE … FOR EACH ROW` en la 003:
  - `turnos`: `BEFORE INSERT … WHEN (NEW.estado IN ('reservado','confirmado'))` y `BEFORE UPDATE OF inicio, fin, profesional_id … WHEN (NEW.estado IN ('reservado','confirmado'))` → `PERFORM pg_advisory_xact_lock(hashtext(NEW.profesional_id::text))`; si existe un bloqueo activo del profesional con `desde < NEW.fin AND hasta > NEW.inicio` → `RAISE … USING ERRCODE = 'exclusion_violation', CONSTRAINT = 'tg_turnos_sin_bloqueo'`.
  - `bloqueos`: `BEFORE INSERT OR UPDATE OF desde, hasta, is_active, profesional_id … WHEN (NEW.is_active)` → mismo lock; si existe un turno `reservado`/`confirmado` del profesional que intersecta → `RAISE … 'exclusion_violation'`, `CONSTRAINT = 'tg_bloqueos_sin_turnos'`.
- **Por qué es correcto bajo concurrencia** (READ COMMITTED): ambos lados toman el **mismo** lock antes de chequear; el segundo espera al commit del primero y, como cada sentencia de una función `VOLATILE` toma un snapshot nuevo, su `EXISTS` ve la fila ya confirmada del ganador. Sin lock, el chequeo de cada trigger no vería la fila no confirmada del otro.
- **Misma clave que C-05**: `uuid::text` de Postgres = `str(uuid)` de Python (minúsculas con guiones) ⇒ `bloquear_agenda` y el trigger serializan entre sí; los advisory locks son reentrantes dentro de la misma transacción (alta manual/reprogramar ya lo tienen, el trigger lo vuelve a pedir sin bloquearse).
- **Sin deadlocks nuevos**: orden global = advisory lock → row lock. `crear_bloqueo`, `alta_manual`, `reprogramar` piden el advisory primero; `reservar_turno` lo pide recién en el `INSERT` del turno (antes solo insertó su paciente: fila nueva, sin contención). `cancelar` y las transiciones de estado (`UPDATE` solo de `estado`) **no** disparan el trigger (`UPDATE OF` excluye `estado`), así que nunca piden el advisory teniendo un row lock.
- **Mapeo a HTTP sin tocar código existente**: `exclusion_violation` = sqlstate `23P01` ⇒ `reservar_turno` ya responde 409 `hueco_ocupado` con huecos; `alta_manual`/`reprogramar` también (`SQLSTATES_DE_CONFLICTO`). `crear_bloqueo` mapea `23P01` → 409 `bloqueo_con_turnos` (D4). Tests de caracterización lo fijan.
- `BEFORE INSERT` corre antes de la inserción especulativa de `ON CONFLICT … DO NOTHING`, así que un turno dentro de un bloqueo da **error** (23P01), no "sin fila": ambas vías terminan en 409.
- El chequeo de aplicación se mantiene (`hay_ocupacion` en turnos; `turnos_activos_en_rango` en bloqueos) para dar 409 con detalle útil; el trigger es el árbitro.
- **Verificación previa en el upgrade**: antes de crear los triggers, la 003 cuenta pares turno activo ↔ bloqueo activo superpuestos y aborta con `RAISE EXCEPTION` si hay alguno (el operador decide qué hacer; nunca se "arreglan" datos solos). `downgrade` borra triggers y funciones.
- Costo: toda reserva pública se serializa por profesional durante el resto de su transacción (milisegundos). Aceptable para una clínica (mismo argumento que C-05 D4).
- Alternativas:
  - (a) Advisory lock solo en la aplicación (`crear_bloqueo` + agregarlo a `reservar_turno`): sigue siendo "solo en la app" (un `INSERT` por otra vía lo saltea) y **modifica `reservar_turno` (CRÍTICO)**. Descartada.
  - (a') Lock solo en `crear_bloqueo` sin tocar la reserva pública: cubre secretaria↔secretaria pero deja la carrera bloqueo ↔ reserva pública. Es el fallback si el usuario rechaza la 003 (OQ-1), documentado como riesgo residual.
  - (c) Aceptar y documentar: contradice la regla dura. Descartada.
  - `SERIALIZABLE` en las escrituras de agenda: tocaría la UoW (CRÍTICO) y agrega reintentos. Descartada.

### D3. Vínculo odontólogo ↔ profesional: `profesionales.user_id` (migración 003) — **requiere aprobación (OQ-1)**

- US-003 CA-2 ("solo su agenda") es imposible sin saber qué profesional es el usuario. Decisión: `profesionales.user_id UUID NULL REFERENCES users(id) ON DELETE RESTRICT` + índice único (`uq_profesionales_user_id`; NULLs múltiples permitidos). En el modelo: `Profesional.user_id: Mapped[uuid.UUID | None]`.
- Lado elegido: el profesional existe sin login (agenda pública); el usuario es opcional. Alternativa `users.profesional_id`: equivalente, pero ensucia `User` (secretarias con columna siempre nula).
- "Solo odontólogos" no se puede expresar como CHECK entre tablas; lo validan la aplicación/el seed y un test. Un odontólogo sin vínculo → 403 `sin_profesional_asociado` (no 404: el recurso existe, el usuario no tiene permiso de verlo).
- Seed sin cambios en C-06 (ver OQ-5).

### D4. Casos de uso de bloqueos (`app/application/bloqueos.py`)

- `crear_bloqueo(uow_factory, datos: BloqueoCreate, *, ahora) -> BloqueoDTO` dentro de `with uow_factory() as session`:
  1. `desde < ahora` → `RangoInvalidoError` (422).
  2. Profesional activo (reusar la consulta de `reservas`/repositorio) → si no, `ProfesionalNoEncontradoError` (404).
  3. `TurnoRepository(session).bloquear_agenda(profesional_id)` (mismo lock que D2; da 409 limpio en vez de depender del trigger).
  4. `BloqueoRepository.turnos_activos_en_rango(profesional_id, desde, hasta) -> list[TurnoEnConflicto]` (`reservado`/`confirmado`, semiabierto, orden por inicio) → si hay, `_BloqueoConTurnos(lista)` interno.
  5. `session.add(Bloqueo(...))` → `flush()` → DTO `frozen`.
  - Fuera del `with`: `_BloqueoConTurnos` → `BloqueoConTurnosError(turnos)`; `DBAPIError` con sqlstate `23P01` (trigger, red de seguridad) → releer `turnos_activos_en_rango` en una **UoW nueva** → `BloqueoConTurnosError`; otro sqlstate se re-lanza (500).
- `dar_de_baja_bloqueo(uow_factory, bloqueo_id, *, ahora) -> BloqueoDTO`: `SELECT … WHERE id AND is_active FOR UPDATE` (`BloqueoRepository.obtener_activo_para_actualizar`) → `None` → `BloqueoNoEncontradoError` (404); `is_active=False`, `deleted_at=ahora`; `flush()`; DTO. No toma el advisory lock (libera agenda; el trigger de `bloqueos` no dispara porque `NEW.is_active` es falso).
- Sin efectos post-commit (no hay cola involucrada). Trazabilidad: `logger.info` estructurado con `accion`, `bloqueo_id`, `profesional_id`, `user_id` en el router tras el retorno (ver OQ-4).

### D5. Reglas de entrada del bloqueo

- `BloqueoCreate`: `profesional_id: UUID`, `desde`/`hasta: AwareDatetime`, `motivo: str` (`str_strip_whitespace`, `min_length=1`, `max_length=200` = la columna), `extra="forbid"`; `model_validator` `hasta > desde` → 422.
- `desde >= ahora` en el caso de uso (`ahora` inyectado por `get_ahora`, tests deterministas). Motivo: los bloqueos son a futuro; evita que un bloqueo "desde esta mañana" choque con turnos ya pasados que siguen `confirmado` porque v1 aún no marca `atendido`. La SPA redondea "desde ahora" al próximo slot.
- Sin alineación a grilla ni duración máxima (un bloqueo de vacaciones puede durar semanas). La agenda semanal acota lo que se lee.
- Bloqueos superpuestos entre sí: **permitidos** (feriado dentro de vacaciones); la disponibilidad ya usa la unión. Una `EXCLUDE` sobre `bloqueos` no protege ningún invariante de negocio y obligaría a partir rangos.

### D6. Agenda (`app/application/agenda.py`, `app/api/agenda.py`)

- **Rango (dominio puro)** `app/domain/agenda.py::rango_agenda(dia: date, vista: Vista) -> tuple[date, date]` (`dia` → `(dia, dia)`; `semana` → lunes..domingo ISO) y `limites_instantes(desde, hasta, tz) -> tuple[datetime, datetime]` = `[desde 00:00 local, (hasta + 1 día) 00:00 local)` con `ZoneInfo(CLINIC_TIMEZONE)` (correcto aun con DST).
- **Lectura** `consultar_agenda(session, *, profesional_id, dia, vista, tz) -> AgendaDTO`: profesional por id (404 si no existe; **inactivo se muestra**, la agenda es histórica para staff); `TurnoRepository.agenda_en_rango(profesional_id, ini, fin)` = **una** query `turnos JOIN pacientes LEFT JOIN tratamientos` por intersección `inicio < fin AND fin > ini`, `ORDER BY inicio, id`, todos los estados; `BloqueoRepository.activos_en_rango` (una query, orden por `desde`). Sin N+1. Solo lectura: `get_db`, `def`, sin UoW ni commit.
- **Contrato (`response_model`, todo `extra="forbid"`)**:
  - `AgendaOut { profesional: {id, nombre}, vista: Literal["dia","semana"], desde: date, hasta: date, turnos: list[AgendaTurnoOut], bloqueos: list[AgendaBloqueoOut] }`
  - `AgendaTurnoOut { id, inicio, fin, estado: Literal[5 estados], origen: Literal["online","secretaria"], sobreturno: bool, paciente: {id, nombre, telefono}, tratamiento: {id, nombre} | None }` — sin `token_publico`.
  - `AgendaBloqueoOut { id, desde, hasta, motivo }`.
  - Instantes con `astimezone(tz)` (offset de la clínica), como el resto de la API.
  - Cancelados **incluidos** (C-10 tiene badge `cancelado`; la SPA filtra). Ver OQ-3.
- **Query params**: `dia: date` (requerido), `vista: Literal["dia","semana"] = "dia"`, `profesional_id: UUID | None = None`. Se mantiene `dia` (nombre de `CHANGES.md`).
- **Autorización** (`app/api/agenda.py`, dependencia `require_staff` nueva en `deps.py` = usuario autenticado con rol `secretaria` u `odontologo`, 401/403):
  - secretaria: `profesional_id` obligatorio → 422 `profesional_requerido` si falta (`ProfesionalRequeridoError`) — evita elegir "un profesional por defecto" implícito.
  - odontólogo: `ProfesionalRepository.por_user_id(user.id)` → `None` → 403 `sin_profesional_asociado`; `profesional_id` ausente → el propio; distinto del propio → 403 `agenda_ajena` (no override silencioso: un id ajeno es un error del cliente que conviene ver). El chequeo ocurre **antes** de leer nada del otro profesional.
- Datos del paciente: `telefono` incluido para ambos roles (staff que atiende/llama); RBAC 03 da al odontólogo "ver propios".

### D7. Errores nuevos (`app/core/exceptions.py`)

- `BloqueoNoEncontradoError(NotFoundError)`: 404 `bloqueo_no_encontrado`.
- `BloqueoConTurnosError(AppError)`: 409 `bloqueo_con_turnos`, `extra()` = `{turnos: [{id, inicio, fin, estado}]}` (ISO con offset).
- `SinProfesionalAsociadoError(AppError)`: 403 `sin_profesional_asociado`.
- `ProfesionalRequeridoError(AppError)`: 422 `profesional_requerido`.
- `AgendaAjenaError(AppError)`: 403 `agenda_ajena` (odontólogo pide otro profesional) — se lanza sin consultar si el id existe.

### D8. Endpoints

| Método y ruta | Auth | Entrada | 2xx | Errores |
|---|---|---|---|---|
| `POST /api/bloqueos` | `require_secretaria` | `BloqueoCreate` | 201 `BloqueoOut` | 401/403/404/409/422 |
| `DELETE /api/bloqueos/{bloqueo_id}` | `require_secretaria` | — | 200 `BloqueoOut` | 401/403/404/422 |
| `GET /api/agenda` | `require_staff` | `dia`, `vista`, `profesional_id` | 200 `AgendaOut` | 401/403/404/422 |

Routers nuevos registrados en `main.py` con prefijo `/api`. Todo `def`. `DELETE` devuelve 200 con cuerpo (como C-05, la SPA refresca sin otra lectura).

### UI Mockups

- Design system revision: n/a
- Decision: no (no UI; la agenda visual es C-10) — 2026-10-30
- Mockups: n/a · Approval: n/a · Preview: n/a · Visual verify: n/a

## Risks / Trade-offs

- [El trigger cambia el comportamiento de `reservar_turno` (CRÍTICO) sin tocar su código: ahora toma el advisory lock y puede recibir 23P01 por bloqueo] → el mapeo 23P01 → 409 ya existe; tests de caracterización de C-04/C-04b siguen verdes; test nuevo "reserva dentro de bloqueo vía constraint → 409". Requiere aprobación (OQ-1).
- [Serialización de reservas públicas por profesional] → transacciones de milisegundos; despreciable para una clínica.
- [Lógica en triggers: menos visible que una constraint] → docstring de la 003, nombres `tg_*` en el `CONSTRAINT` del error, tests de migración que insertan por SQL.
- [Datos previos inconsistentes abortan el upgrade] → intencional (nunca se corrigen datos solos); en entornos actuales no hay bloqueos (no había endpoint).
- [Vínculo usuario↔profesional sin endpoint de administración] → por seed/SQL hasta un change de ABM de staff; documentado.
- [403 vs 404 para odontólogo con profesional ajeno] → 403 no revela existencia del id (no se lee nada antes del chequeo).
- [Bloqueo que empieza "ahora" rechazado por segundos de diferencia] → la SPA redondea al próximo slot; mensaje 422 accionable.
- [Sin auditoría persistente de bloqueos] → log estructurado; OQ-4.

## Migration Plan

1. **Migración 003** `003_bloqueos_sin_turnos_y_profesional_user.py` (escrita a mano, diff revisable): (a) `ADD COLUMN profesionales.user_id` + FK + índice único; (b) verificación de pares turno↔bloqueo superpuestos (aborta si hay); (c) funciones `turno_sin_bloqueo()` / `bloqueo_sin_turnos()` + 3 triggers. `downgrade`: triggers → funciones → índice/columna.
2. Sin variables de entorno nuevas. Sin dependencias nuevas.
3. Deploy: `alembic upgrade head` antes de levantar el backend nuevo (el backend viejo es compatible con la 003: la columna es nullable y los triggers solo agregan 409 que ya sabe mapear).
4. Rollback: `alembic downgrade 002` + revertir el commit; los bloqueos creados quedan válidos para la 002.
5. **Si OQ-1 se rechaza**: sin 003 ⇒ D2 cae a la alternativa (a') (lock solo en `crear_bloqueo`, riesgo residual documentado con la reserva pública) y D3 queda sin implementar ⇒ `GET /api/agenda` solo para secretaria y US-003 pasa a otro change.

## Open Questions

Resueltas con el usuario (2026-10-30), todas según la recomendación del diseño:

- **OQ-1 — Migración 003**: **DECIDIDO — sí, migración 003** con triggers turno↔bloqueo (D2) + `profesionales.user_id` (D3). Registrado como DD-08 y DD-09.
- **OQ-2 — Bloqueo sobre turnos activos**: **DECIDIDO — rechazar con 409 `bloqueo_con_turnos` listando los turnos** (D1). DD-10.
- **OQ-3 — Cancelados en la agenda**: **DECIDIDO — la agenda siempre los incluye** (la SPA filtra). DD-11.
- **OQ-4 — Trazabilidad de bloqueos**: **DECIDIDO — solo log estructurado en v1** (sin columnas ni tabla nuevas). DD-12.
- **OQ-5 — Odontólogo de ejemplo en el seed**: **DECIDIDO — no en C-06**; los tests crean el vínculo.

Decididas en este diseño (sin input requerido): bloqueos superpuestos entre sí permitidos (D5); baja lógica con 404 si ya inactivo (D4); `desde >= ahora` (D5); odontólogo con profesional ajeno → 403, sin override (D6); profesional inactivo visible en la agenda (D6); parámetro `dia` + `vista=dia|semana` (D6).
