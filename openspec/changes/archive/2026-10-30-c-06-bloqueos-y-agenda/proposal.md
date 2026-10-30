# Proposal: c-06-bloqueos-y-agenda

> Governance: **MEDIO** (lógica de agenda: implementar con checkpoints y exponer decisiones). **Dos puntos requieren aprobación explícita del usuario antes del apply** (ver `design.md` — Open Questions): (1) una **migración 003**, que contradice el "sin migración nueva" de `CHANGES.md` pero la exige la regla dura de anti-solape en la base y el vínculo odontólogo↔profesional que hoy no existe; (2) el trigger de la 003 cambia, **a nivel base**, el comportamiento de `reservar_turno` (CRÍTICO), aunque su código Python no se toca.

## Why

La secretaria no puede marcar vacaciones, feriados ni ausencias (RN-AG-02): la tabla `bloqueos` existe desde la 002 y la disponibilidad ya la respeta, pero no hay forma de crearla ni darla de baja. Tampoco existe una vista de agenda interna: US-002 (secretaria, día/semana por profesional, estados y origen) y US-003 (odontólogo, solo su agenda) no tienen endpoint, y C-10 (SPA de agenda, camino crítico) los consume.

Al revisar el código aparecieron dos huecos que este change no puede esquivar:

- **Carrera bloqueo ↔ turno**: no hay garantía en la base de que un turno no caiga dentro de un bloqueo. `hay_ocupacion` lo chequea en la aplicación, pero un bloqueo y una reserva concurrentes pueden solaparse. Una `EXCLUDE` no cruza dos tablas. La regla dura "NUNCA validar anti-solape solo en la app" pide una garantía en Postgres.
- **Odontólogo sin profesional**: `users` y `profesionales` no están vinculados (ni FK ni columna). "El odontólogo ve solo su agenda" (US-003 CA-2) es imposible de implementar sin agregar ese vínculo.

## What Changes

- **Alta de bloqueo** `POST /api/bloqueos` (solo `secretaria`): `profesional_id`, `desde`, `hasta` (con zona), `motivo` (1–200, obligatorio). 201 con el bloqueo. 404 profesional inexistente/inactivo; 422 por rango inválido o que empieza en el pasado.
- **Bloqueo sobre turnos activos rechazado**: si el rango pisa turnos `reservado`/`confirmado` del profesional → 409 `bloqueo_con_turnos` con la lista de esos turnos (id, inicio, fin, estado). La secretaria los reprograma/cancela (C-05) y reintenta. Bloqueos superpuestos entre sí **se permiten**.
- **Baja de bloqueo** `DELETE /api/bloqueos/{id}` (solo `secretaria`): baja lógica (`is_active=false`, `deleted_at`); el rango vuelve a la disponibilidad. 404 si no existe o ya estaba dado de baja.
- **Garantía en la base turno ↔ bloqueo** (migración 003): triggers sobre `turnos` y `bloqueos` que toman el mismo advisory lock por profesional que C-05 (`pg_advisory_xact_lock(hashtext(profesional_id::text))`) y rechazan con `23P01` (exclusion violation) un turno activo dentro de un bloqueo activo y viceversa. Cubre **todas** las vías de escritura (reserva pública incluida) sin tocar su código: `23P01` ya se mapea a 409.
- **Vínculo odontólogo ↔ profesional** (migración 003): `profesionales.user_id` nullable, único, FK a `users`.
- **Agenda interna** `GET /api/agenda?dia=YYYY-MM-DD&vista=dia|semana&profesional_id=…` (staff): turnos del rango ordenados por inicio con paciente, tratamiento, estado, origen y sobreturno (incluidos cancelados, para los badges de C-10) + bloqueos activos del rango. Semana = lunes a domingo que contiene `dia`, en `CLINIC_TIMEZONE`. Sin `token_publico`.
- **Aislamiento por rol**: secretaria ve cualquier profesional (`profesional_id` obligatorio); odontólogo ve solo el suyo (sin `profesional_id` → el propio; con uno ajeno → 403; sin profesional vinculado → 403 `sin_profesional_asociado`).
- **Errores nuevos** (`AppError`): `BloqueoNoEncontradoError` (404), `BloqueoConTurnosError` (409), `SinProfesionalAsociadoError` (403), `AgendaAjenaError` (403), `ProfesionalRequeridoError` (422).

## Capabilities

### New Capabilities
- `bloqueos`: alta y baja lógica de bloqueos por secretaria, rechazo sobre turnos activos e invariante turno↔bloqueo garantizado por la base bajo concurrencia.

### Modified Capabilities
- `agenda`: nueva vista interna de agenda día/semana por profesional, con aislamiento por rol.
- `core-models`: vínculo opcional y único entre un `Profesional` y un `User` odontólogo.

## Impact

- **Código nuevo**: `app/application/bloqueos.py` (`crear_bloqueo`, `dar_de_baja_bloqueo` + DTO), `app/application/agenda.py` (`consultar_agenda` + DTO), `app/api/bloqueos.py`, `app/api/agenda.py`, `alembic/versions/003_bloqueos_sin_turnos_y_profesional_user.py`.
- **Código modificado (aditivo)**: `app/infrastructure/repositories_agenda.py` (`BloqueoRepository.turnos_activos_en_rango`/`obtener_activo`, `TurnoRepository.agenda_en_rango` con join a paciente/tratamiento), `app/infrastructure/models.py` (`Profesional.user_id`), `app/domain/schemas.py`, `app/core/exceptions.py`, `app/main.py` (routers), `app/api/deps.py` (dependencia de staff autenticado: secretaria u odontólogo).
- **Sin cambios de código** en `reservar_turno` ni en `gestion_turnos.py`; cambia su comportamiento solo en que un turno dentro de un bloqueo concurrente ahora es 409 por la base (antes podía colarse).
- **DB**: migración **003** (columna + índice único + 2 funciones/triggers + verificación previa de datos). **Dependencias**: ninguna nueva. **Env vars**: ninguna nueva.
- **Tests**: dominio (rango semanal), repositorio, migración 003, casos de uso, API por rol, concurrencia (`threading.Barrier`) bloqueo vs reserva pública / alta manual / reprogramación. Los 396 existentes siguen verdes sin cambiar aserciones.
