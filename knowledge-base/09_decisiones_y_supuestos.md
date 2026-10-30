# Decisiones y Supuestos

## Decisiones documentadas

### DD-01 — Single-clínica en v1, patrones preparados para escalar
**Decisión**: un deploy por clínica, sin multi-tenant en v1.
**Contexto**: escala equipo pequeño + prioridad escalabilidad (tensión explícita).
**Alternativas consideradas**: SaaS multi-tenant desde día 1; monolito sin capas.
**Justificación**: velocidad v1 sin resignar evolución (capas + migraciones + auditoría).
**Trade-offs aceptados**: un segundo deploy por clínica; la migración a
multi-tenant será un change dedicado.

### DD-02 — Stack FastAPI + React impuesto por el usuario
**Decisión**: Python/FastAPI/JWT/SQLAlchemy/Postgres/Redis/Docker +
React/TS/Vite.
**Contexto**: restricción dada en ronda kb-creator (antes: sin stack impuesto).
**Alternativas consideradas**: monolito full-stack único.
**Justificación**: estándar productivo, async para WA, SPA mobile-first.
**Trade-offs aceptados**: dos codebases (api + web) desde el inicio.

### DD-03 — Reserva pública sin login obligatorio en v1
**Decisión**: nombre + teléfono + token por turno.
**Contexto**: fricción cero para el paciente (Discovery: pregunta abierta).
**Alternativas consideradas**: login paciente obligatorio.
**Justificación**: maximiza conversión de reserva; el token limita el riesgo.
**Trade-offs aceptados**: posible duplicación de pacientes (a deduplicar después).

### DD-04 — WhatsApp solo envío en v1
**Decisión**: recordatorio 24hs + confirmación 1-clic, sin bot conversacional.
**Contexto**: mercado AR cobra WA por uso; bot suma costo y complejidad.
**Justificación**: ataca el no-show con el menor costo.
**Trade-offs aceptados**: sin lista de espera automática ni reprogramación por chat.

### DD-05 — Secretaria exenta de la anticipación mínima (2026-10-30)
**Decisión**: RN-TU-01 aplica solo al paciente por token; la secretaria (JWT staff) puede cancelar/reprogramar sin anticipación mínima.
**Contexto**: la secretaria gestiona urgencias y cambios de último momento; RN-TU-01 no distinguía actor.
**Justificación**: la operación real de la clínica lo requiere; la acción queda auditada (AuditoriaTurno).
**Trade-offs aceptados**: sin freno de anticipación para el staff; se confía en la auditoría.

### DD-06 — Alta manual reusa Paciente por teléfono normalizado (2026-10-30)
**Decisión**: al crear un turno a mano se busca el Paciente por teléfono normalizado; solo si no existe se crea.
**Contexto**: DD-03 aceptó posible duplicación de pacientes; el alta manual es el punto donde se puede evitar.
**Justificación**: evita duplicados sin exigir DNI ni login.
**Trade-offs aceptados**: dos personas que comparten teléfono (p. ej. familia) se unifican en un Paciente.

### DD-07 — Reprogramar un turno confirmado lo devuelve a reservado (2026-10-30)
**Decisión**: reprogramar un turno `confirmado` lo pasa a `reservado` (el paciente debe reconfirmar) y el recordatorio se re-encola post-commit.
**Contexto**: RN-TU-04 no tenía transición confirmado → reservado ni definía el estado tras reprogramar.
**Justificación**: la confirmación era para el horario anterior; reconfirmar reduce no-shows.
**Trade-offs aceptados**: un paso extra para el paciente; requiere agregar la transición a la máquina de estados.

### DD-08 — Migración 003: triggers anti-solape turno↔bloqueo (2026-10-30)
**Decisión**: la migración 003 agrega triggers en `turnos` y `bloqueos` que rechazan (sqlstate 23P01) un turno activo dentro de un bloqueo activo y viceversa, serializados con el mismo advisory lock por profesional que `bloquear_agenda` (C-05).
**Contexto**: una EXCLUDE no cruza tablas; bloqueo y reserva concurrentes podían confirmar ambos. La regla dura exige anti-solape en Postgres.
**Justificación**: garantiza el invariante para todas las vías de escritura sin tocar `reservar_turno` (CRÍTICO).
**Trade-offs aceptados**: lógica en triggers (menos visible); las reservas públicas se serializan por profesional durante milisegundos; el upgrade aborta si ya hay datos inconsistentes.

### DD-09 — Vínculo odontólogo↔profesional: `profesionales.user_id` (2026-10-30)
**Decisión**: columna nullable, única, FK a `users` (ON DELETE RESTRICT) en `profesionales`, agregada en la 003.
**Contexto**: US-003 ("solo su agenda") requiere saber qué profesional es el usuario; no había vínculo.
**Justificación**: el profesional existe sin login; evita una columna casi siempre nula en `users`.
**Trade-offs aceptados**: sin endpoint de administración (vínculo por seed/SQL hasta un change de ABM); "solo odontólogos" lo valida la aplicación, no la base.

### DD-10 — Bloqueo sobre turnos activos se rechaza con 409 (2026-10-30)
**Decisión**: crear un bloqueo que pisa turnos `reservado`/`confirmado` responde 409 `bloqueo_con_turnos` con la lista de turnos; la secretaria los reprograma/cancela y reintenta.
**Contexto**: la KB no definía qué pasa con turnos preexistentes.
**Justificación**: evita turnos vivos en un rango sin atención y hace el invariante bidireccional.
**Trade-offs aceptados**: un paso manual extra para la secretaria; no se cancela automáticamente (efecto masivo).

### DD-11 — La agenda incluye siempre los turnos cancelados (2026-10-30)
**Decisión**: `GET /api/agenda` devuelve todos los estados; la SPA filtra.
**Contexto**: C-10 muestra badge `cancelado`.
**Justificación**: contrato simple y estable; sin parámetros extra.
**Trade-offs aceptados**: payload algo mayor.

### DD-12 — Trazabilidad de bloqueos por log estructurado (2026-10-30)
**Decisión**: alta/baja de bloqueos se registran con `logger.info` estructurado (`accion`, `bloqueo_id`, `profesional_id`, `user_id`); sin `created_by` ni tabla de auditoría en v1.
**Contexto**: `bloqueos` no tiene autoría.
**Justificación**: evita ampliar el modelo; suficiente para v1.
**Trade-offs aceptados**: sin auditoría persistente consultable.

## Supuestos inferidos

### SU-01 — Anticipación mínima 24h
**Supuesto**: default 24h configurable.
**Origen**: Discovery (supuesto inicial; caso real AgendaPro usa 3h).
**Riesgo si es falso**: reglas de cancelación molestas o laxas.
**Cómo validar**: preguntar a la clínica antes del seed.

### SU-02 — Redis solo para jobs de notificación
**Supuesto**: sin caché general en v1.
**Origen**: respuesta de arquitectura (jobs async).
**Riesgo si es falso**: sobredimensionar infra.
**Cómo validar**: medir disponibilidad bajo carga en staging.

### SU-03 — Un sillón = un profesional en v1
**Supuesto**: sin gestión explícita de sillones/boxes (vacío de mercado).
**Origen**: Discovery (no documentado por competidores AR).
**Riesgo si es falso**: choques de recursos físicos.
**Cómo validar**: confirmar si la clínica comparte sillones.
