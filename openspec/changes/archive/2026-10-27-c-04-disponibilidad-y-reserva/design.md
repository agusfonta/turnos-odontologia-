# Design: c-04-disponibilidad-y-reserva

## Context
Estado verificado en `src/backend/app/`:
- `core/db.py`: `Base`, `SessionLocal` y `get_db` sincrónicos (psycopg 3). `core/settings.py`: `CLINIC_TIMEZONE`, `CANCEL_MIN_HOURS`, `REDIS_URL`. `core/exceptions.py`: `AppError(status_code, code, detail)` → JSON `{detail, code}`.
- `infrastructure/models.py`: `Profesional` (UUID, `slot_default_min`, `activo ≡ is_active`), `Paciente` (CHECK E.164), `Tratamiento` (id entero identity, `duracion_min`), `User` (`rol` enum `user_role`). `BaseRepository[T]` + `UnitOfWork` sincrónicos. `domain/phone.py`: `E164_PATTERN`/`TelefonoE164` como única fuente de la regex.
- `api/deps.py`: `get_current_user` (OAuth2 bearer obligatorio), `require_secretaria`. `core/security.py` ya crea clientes Redis con `redis.Redis.from_url`.
- Alembic: `versions/001_core_tables.py` escrita a mano (`revision="001"`). Tests de DB con `tests/support.require_pg()` (skip explícito si no hay PG); `fakeredis` ya está en requirements.
- `application/` está vacío: C-04 es el primer caso de uso real.

Motivación y scope: ver `proposal.md`. Comportamiento exigido: `specs/agenda/spec.md` y `specs/turnos/spec.md`.

## Goals / Non-Goals

**Goals:**
- Invariante anti-solape en Postgres (no solo en app), con la app traduciendo la violación a 409.
- Cálculo de huecos como función pura de dominio, testeable sin DB, reutilizada por la consulta, la validación del POST y el cuerpo del 409.
- Transacción de reserva corta y atómica (paciente + turno + auditoría); efectos externos (Redis) después del commit.
- Contratos estables para C-05 (estados, `sobreturno`), C-06 (`bloqueos`, `horario_profesional`), C-07 (`token_publico`) y C-08 (formato del job).

**Non-Goals:**
- Locks pesimistas / aislamiento SERIALIZABLE (la exclusion constraint alcanza para turno-vs-turno).
- Cache de disponibilidad (SU-02: Redis solo para jobs).
- Endpoints de transición de estado (la máquina de estados queda en dominio; la usan C-05/C-07).

## Decisions

1. **Exclusion constraint `btree_gist` sobre `tstzrange` por profesional.**
   `CREATE EXTENSION IF NOT EXISTS btree_gist;` + `ALTER TABLE turnos ADD CONSTRAINT ex_turnos_sin_solape EXCLUDE USING gist (profesional_id WITH =, tstzrange(inicio, fin, '[)') WITH &&) WHERE (estado <> 'cancelado' AND NOT sobreturno);` + `CHECK (fin > inicio)`.
   - Por qué: regla dura (anti-solape nunca solo en app) y RN-AG-01; `[)` permite turnos contiguos; el `WHERE` libera huecos cancelados y deja preparado el sobreturno explícito de C-05 (RN-AG-04) sin otra migración.
   - Alternativas: check en app + `SELECT … FOR UPDATE` (descartada: no es invariante de DB, falla ante otro camino de escritura); `SERIALIZABLE` (descartada: reintentos por toda la app, más complejo y no expresa la regla); trigger custom (descartada: más código, misma garantía que la constraint nativa).
   - Privilegios: `btree_gist` es *trusted* desde PG 13 → la crea cualquier rol con `CREATE` sobre la DB. Si el rol de deploy no lo tiene, pre-crearla como DBA (documentado en Migration Plan). Downgrade **no** borra la extensión (puede ser compartida; dejarla es inocuo).

2. **Columna `sobreturno BOOLEAN NOT NULL DEFAULT false` en 002, nunca `true` en C-04.** Evita que C-05 necesite migración para RN-AG-04 (C-05/C-06 están planificados sin migración nueva). C-04 la omite en el schema de entrada (no hay campo fantasma: no se acepta del cliente).

3. **Turno sin `AuditMixin`.** `turnos` lleva `created_at`/`updated_at` (timestamptz, `server_default now()`), pero no `is_active`/`deleted_at`: la baja de un turno es `estado=cancelado` (un `is_active=false` con estado `reservado` rompería la constraint y la semántica). `bloqueos` **sí** usa `AuditMixin` (C-06 hace baja lógica; disponibilidad filtra `is_active`). `auditoria_turno` solo `created_at`.

4. **Esquema de 002** (escrita a mano, `revision="002"`, `down_revision="001"`):
   - Enums Postgres `turno_estado ('reservado','confirmado','cancelado','ausente','atendido')`, `turno_origen ('online','secretaria')`, `auditoria_actor ('paciente','secretaria','odontologo','sistema')`.
   - `turnos`: `id UUID PK`, `profesional_id UUID FK→profesionales RESTRICT`, `paciente_id UUID FK→pacientes RESTRICT`, `tratamiento_id INT NULL FK→tratamientos RESTRICT`, `inicio/fin timestamptz NOT NULL`, `estado`, `origen`, `sobreturno`, `token_publico VARCHAR(64) NULL UNIQUE`, `created_by UUID NULL FK→users`, timestamps. Índices `(profesional_id, inicio)`, `(estado)`, `(paciente_id)`.
   - `bloqueos`: `id UUID PK`, `profesional_id FK`, `desde/hasta timestamptz`, `motivo VARCHAR(200) NOT NULL`, `AuditMixin`; `CHECK (hasta > desde)`; índice `(profesional_id, desde) WHERE is_active`.
   - `auditoria_turno`: `id UUID PK`, `turno_id FK RESTRICT`, `accion VARCHAR(32) NOT NULL`, `actor_tipo auditoria_actor`, `actor_user_id UUID NULL FK→users`, `detalle JSONB NOT NULL DEFAULT '{}'`, `created_at`; índice `(turno_id, created_at)`.
   - `horario_profesional` (ver Decisión 6): `id UUID PK`, `profesional_id UUID FK→profesionales RESTRICT`, `dia_semana SMALLINT NOT NULL CHECK (dia_semana BETWEEN 0 AND 6)`, `hora_inicio/hora_fin TIME NOT NULL` (sin zona: hora local de la clínica), `CHECK (hora_fin > hora_inicio)`, `AuditMixin`; exclusion `ex_horario_sin_solape`; índice `(profesional_id, dia_semana) WHERE is_active`.
   - **Append-only en DB**: función `auditoria_turno_inmutable()` + trigger `BEFORE UPDATE OR DELETE` que hace `RAISE EXCEPTION`. Por qué: Ley 25.326 / RN-GL-01 con governance CRÍTICO; un `REVOKE` dependería de roles del deploy. Trade-off: un borrado legítimo (p.ej. derecho de supresión) requerirá desactivar el trigger en un change explícito.
   - `downgrade()`: drop trigger/función → tablas (orden inverso de FKs) → enums → tipo `timerange`. Modelos SQLAlchemy espejan la migración; nunca `create_all`.

5. **Huecos como función pura de dominio** (`domain/disponibilidad.py`): `calcular_huecos(dias, franjas, paso_min, duracion_min, ocupados, ahora, tz) -> list[Hueco]`. Para cada día local del rango toma las franjas activas de ese `dia_semana` (`date.weekday()`, 0=lunes) y genera, **por franja**, la grilla desde su `hora_inicio` con paso `slot_default_min` exigiendo `inicio + duración <= hora_fin` de la misma franja (un hueco nunca cruza de una franja a otra, aunque sean contiguas); sin franjas → lista vacía. Luego descarta `inicio <= ahora` y todo hueco que intersecte `[inicio, fin)` de algún ocupado. Por qué: testeable sin DB y una sola definición de "hueco real" para GET, validación del POST y el 409. La capa de aplicación trae `ocupados` con **una** query por tabla (turnos no cancelados + bloqueos activos que intersectan el rango, solo columnas `inicio/fin`), sin N+1. Construcción con `zoneinfo` sobre fechas locales para que los cambios de offset no corran la grilla (`tzdata` en requirements para Windows/CI).

6. **Horarios por profesional en tabla `horario_profesional` (decisión del usuario 2026-10-27, A1)**. Franjas semanales recurrentes; varias por día (p.ej. 09–13 y 15–19). Las horas son `TIME` sin zona y se interpretan como hora local de `CLINIC_TIMEZONE`: el instante se arma con `datetime.combine(fecha_local, hora, tzinfo=ZoneInfo(tz))` (Argentina no tiene DST hoy, pero se usa `zoneinfo` igual para que un cambio de régimen no rompa la grilla).
   - **Sin solape en DB**: `CREATE TYPE timerange AS RANGE (subtype = time)` + `EXCLUDE USING gist (profesional_id WITH =, dia_semana WITH =, timerange(hora_inicio, hora_fin, '[)') WITH &&) WHERE (is_active)`. Por qué un tipo de rango propio: Postgres no trae rango de `time`; el constructor de un range type es inmutable (apto para índice) y expresa la regla tal cual. Alternativa considerada: `int4range` de minutos vía `EXTRACT` (descartada: expresión menos legible y depende de la inmutabilidad de `extract` sobre `time`). `[)` permite franjas contiguas (09–13 y 13–17). `WHERE is_active` deja dar de baja una franja y crear otra que la reemplace (C-06). Crear un tipo no requiere superusuario; reutiliza `btree_gist` de la Decisión 1 para los `=`.
   - Franjas que cruzan medianoche: no soportadas (`hora_fin > hora_inicio`); una clínica no las necesita.
   - Settings: **no** se agregan `AGENDA_HORA_INICIO/FIN/DIAS_HABILES`; solo `DISPONIBILIDAD_MAX_DIAS = 31`.
   - Lectura: la capa de aplicación trae las franjas activas del profesional con **una** query (`HorarioRepository.activas_por_profesional`) y las pasa al dominio.
   - Alternativa descartada: horario global por settings (A1 original, rechazado por el usuario).

7. **Flujo de `POST /api/turnos` (caso de uso `reservar_turno`, todo `def`)**, en una sola `UnitOfWork`:
   1. Pydantic estricto (`extra="forbid"`; `inicio: AwareDatetime`; `TelefonoE164`; nombre 1–200) → 422.
   2. Profesional activo (404), tratamiento activo si viene (404); duración = tratamiento o slot.
   3. Validación de grilla/franja/pasado con la misma lógica del dominio (`inicio` debe ser un punto de grilla de alguna franja activa y `inicio + duración` caber en esa franja; profesional sin franjas → siempre inválido) → 422 (`code=inicio_invalido`).
   4. Chequeo de ocupación (turnos + bloqueos) → `HuecoOcupadoError` (409).
   5. Inserta `Paciente`, `Turno` (`token_publico = secrets.token_urlsafe(32)`), `AuditoriaTurno(accion="crear")`; `flush()`.
   6. Si el flush/commit lanza `IntegrityError` con `sqlstate 23P01` (exclusion_violation) → rollback y `HuecoOcupadoError` (es la carrera real entre consulta y alta). Otras `IntegrityError` se propagan (500, bug).
   7. Commit. Recién después, encolar recordatorio (Decisión 9).
   El 409 se arma fuera de la transacción fallida: nueva lectura de huecos del mismo día local y misma duración → `{detail, code:"hueco_ocupado", huecos:[...]}` (extensión de `AppError` con payload tipado). Por qué app-check + constraint: el check da el 409 "lindo" y cubre bloqueos (no expresables como exclusion entre tablas); la constraint es la garantía bajo concurrencia.

8. **Auth opcional en el mismo endpoint**: nueva dependencia `get_optional_staff` con `OAuth2PasswordBearer(auto_error=False)`: sin header → `None` (online); header presente → se reutiliza la validación de `get_current_user` (401 si inválido) y se exige rol `secretaria` (403 si no). Nunca se degrada a público ante token inválido (evita que un error de sesión de la secretaria cree turnos `online` sin `created_by`). Alternativa (`/api/turnos/manual` aparte) es la de C-05 con paciente existente; aquí el scope pide un solo endpoint.

9. **Encolado de recordatorio en Redis, post-commit y tolerante a fallas** (`infrastructure/jobs.py`, `RecordatorioQueue`): `ZADD jobs:recordatorios {turno_id} score=epoch(inicio − 24h)` (sorted set como cola diferida; `turno_id` como miembro → idempotente). Reintento acotado (3 intentos, backoff 50/100 ms, `socket_timeout` corto); si falla, `logger.warning` con `turno_id` y se responde 201 igual. Por qué: regla dura (WA nunca en request; el turno no depende del envío) y RN-NO-01. Sin librería de colas nueva: el worker y su política (turnos a < 24 h, estados cancelados, reconciliación de turnos sin job) se definen en C-08. El encolador se inyecta como dependencia para reemplazarlo por `fakeredis`/fake que falla en tests.
   - Alternativa: outbox en Postgres (descartada en C-04: la tabla `notificacion` es de la migración 003/C-08; C-08 debería agregar un barrido de reconciliación para jobs perdidos — se deja anotado).

10. **Máquina de estados en dominio** (`domain/turno_estados.py`): `TRANSICIONES: dict[EstadoTurno, frozenset[EstadoTurno]]` + `transicionar(actual, nuevo) -> EstadoTurno` que lanza `TransicionInvalidaError`. Sin endpoint en C-04; DB solo valida el enum (las transiciones no se expresan con CHECK). C-05/C-07 la invocan y auditan.

11. **Capas y routers**: `api/profesionales.py`, `api/tratamientos.py`, `api/disponibilidad.py`, `api/turnos.py` con `APIRouter(prefix=..., tags=[...])`, params `Annotated[...]`, `response_model`/tipo de retorno siempre, status 201 en el POST, montados en `main.py` con prefijo `/api`. Schemas HTTP en `api/schemas/` (o `domain/schemas.py` si se sigue el patrón actual) con `extra="forbid"`; `ProfesionalPublico` sin matrícula; `TratamientoPublico` con solo `id`, `nombre`, `duracion_min` (A6), listando activos vía `BaseRepository.list` (excluye inactivos/soft-deleted por defecto), orden por nombre. Repos específicos (`TurnoRepository`, `BloqueoRepository`, `HorarioRepository`) extienden `BaseRepository` con queries de intervalo. Todo sincrónico.

12. **Tests**: dominio puro (huecos, estados) sin DB; integración con `TestClient` + Postgres real vía `require_pg()` y migración aplicada (`alembic upgrade head` en el fixture), limpiando por transacción/TRUNCATE; concurrencia con 2 threads + `threading.Barrier`, cada uno con su propia sesión/cliente, contra PG real. Redis con `fakeredis` y un fake que lanza `ConnectionError`. Reloj inyectable (`ahora`) para que los tests no dependan de la fecha real. Datos 100% sintéticos (`+5491100000000`-style ficticios, nombres genéricos).

13. **Seed de C-02 reutilizado y extendido** (`infrastructure/seed.py`, `run_seed`): se agrega la carga de franjas lunes–viernes 09:00–13:00 y 15:00–19:00 para el profesional de ejemplo, con get-or-create por clave natural `(profesional_id, dia_semana, hora_inicio, hora_fin)` → idempotente (doble corrida = mismos conteos). Solo datos sintéticos; sigue siendo CLI explícito, sin auto-run.

## Risks / Trade-offs
- [Rol de deploy sin privilegio para `CREATE EXTENSION`] → `btree_gist` es trusted (PG ≥ 13); si falla, la migración aborta limpio y el DBA la crea una vez. Documentado.
- [Carrera bloqueo-vs-turno] → no hay constraint cruzada entre tablas; en C-04 no se crean bloqueos por API, así que no hay carrera real. **C-06** debe serializar alta de bloqueo vs reserva (p.ej. `pg_advisory_xact_lock` por profesional en ambos caminos) y definir qué pasa con turnos existentes dentro de un bloqueo nuevo.
- [Pérdida de job si Redis cae] → turno queda sin recordatorio; mitigado con reintento + warning; C-08 debe reconciliar (turnos futuros sin notificación).
- [Token en claro en DB] → necesario para armar links en C-08; 256 bits de entropía, `UNIQUE`, nunca logueado ni expuesto en listados. Hashearlo exigiría pasar el token por Redis (peor).
- [Abuso del POST público (spam de reservas)] → fuera de scope; C-11 (rate limit por IP/teléfono). Se acepta en v1.
- [Paciente duplicado por reserva] → aceptado por DD-03; dedup en C-05/C-11.
- [Grilla con paso `slot_default_min` puede dejar huecos inutilizados con tratamientos largos] → trade-off aceptado por simplicidad y predictibilidad para el paciente.
- [Profesional activo sin franjas no recibe reservas] → comportamiento buscado (`200 []`, POST 422); hasta que C-06 traiga el ABM, las franjas se cargan por seed o SQL de datos. Riesgo operativo: olvidar cargar horarios de un profesional nuevo → C-06 debería avisarlo en la UI.
- [Cambio de franjas con turnos ya reservados fuera del nuevo horario] → C-04 no edita franjas; **C-06** debe definir la política (impedir la baja o listar turnos afectados).
- [Tipo `timerange` propio en el esquema] → un objeto más a mantener; se elimina en el downgrade y queda documentado en la migración.
- [Tests de DB que hacen skip sin Postgres local] → CI ya corre con servicio PG (C-02); la suite de concurrencia es obligatoria en CI.

## Migration Plan
1. Verificar/crear `btree_gist` (automático en 002; manual por DBA si el rol no tiene `CREATE`).
2. `alembic upgrade head` (001 → 002). Rollback: `alembic downgrade 001` elimina trigger, función, tablas, enums y el tipo `timerange` de 002 (la extensión queda).
3. Cargar franjas: `python -m app.infrastructure.seed` (idempotente) en dev; en producción, cargar las franjas reales de cada profesional (SQL de datos revisado) hasta que C-06 provea el ABM. Sin variables de entorno nuevas obligatorias (`DISPONIBILIDAD_MAX_DIAS` tiene default).
4. Deploy del backend; sin cambios de frontend.

## Open Questions
- Ninguna. Supuestos aprobados por el usuario 2026-10-27 (A2–A5, A7; A1 reemplazado por horarios por profesional; A6 resuelto incluyendo `GET /api/tratamientos`).
