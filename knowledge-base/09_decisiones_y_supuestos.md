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
