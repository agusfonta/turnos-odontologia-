# Proposal: c-05-gestion-secretaria-turnos

> Governance: **MEDIO** (lógica de negocio de turnos: implementar con checkpoints y exponer decisiones). No toca el contrato de `reservar_turno` (eso sería CRÍTICO): los casos de uso nuevos viven aparte y reusan helpers con cambios **aditivos** (kwargs opcionales con default). **Sin migración de DB**: la columna `turnos.sobreturno` y la exclusión parcial `ex_turnos_sin_solape` ya existen desde la 002.

## Why

La secretaria hoy solo puede reservar por el mismo endpoint público (`POST /api/turnos` con JWT), que siempre crea un paciente nuevo y no admite sobreturnos; no puede mover ni cancelar turnos. Flujo 2 (gestión telefónica/presencial, US-006 y la parte de reprogramar/cancelar de US-005) es el corazón operativo de la clínica y es prerrequisito de la agenda interna (C-10, camino crítico). C-04b ya fijó el patrón UoW + DTO + efectos post-commit que este change copia.

## What Changes

- **Alta manual** `POST /api/turnos/manual` (solo `secretaria`, 401/403 si no): reusa el `Paciente` existente por teléfono normalizado y lo crea solo si no existe (DD-06); `origen=secretaria`, `created_by` = usuario; mismas validaciones de hueco que la reserva; 201 con `token_publico`.
- **Sobreturno explícito** (RN-AG-04): campo `sobreturno: bool = false` en el alta manual y en la reprogramación. Sin la marca, el solape → 409 `hueco_ocupado`; con la marca (solo secretaria, ya garantizado por el router y revalidado en el caso de uso) se omite el chequeo de ocupación por turnos y la exclusión de la base lo exime (`NOT sobreturno`). Nunca exime de bloqueos ni de la grilla/franja. Queda auditado.
- **Reprogramar** `PATCH /api/turnos/{turno_id}` (solo `secretaria`): nuevo `inicio` (y `sobreturno` opcional); revalida el hueco excluyendo el propio turno; un turno `confirmado` vuelve a `reservado` (DD-07); 409 por solape, 422 por inicio inválido/estado terminal, 404 si no existe; re-encola el recordatorio con el nuevo `inicio` **post-commit**.
- **Cancelar** `DELETE /api/turnos/{turno_id}` (solo `secretaria`): pasa a `cancelado` (baja lógica, libera el hueco); 422 si el estado es terminal; quita el recordatorio de la cola (`ZREM`) **post-commit**.
- **Anticipación mínima por actor** (RN-TU-01 + DD-05): el paciente (puerta por token, C-07) queda sujeto a `CANCEL_MIN_HOURS`; la secretaria está **exenta**, pero nunca puede mover/cancelar un turno que ya empezó (422). La exención queda registrada en la auditoría. El caso de uso ya recibe el actor para que C-07 solo agregue la puerta.
- **Concurrencia**: el alta manual delega el anti-solape en la exclusión de la base (`INSERT … ON CONFLICT ON CONSTRAINT ex_turnos_sin_solape DO NOTHING`, igual que la reserva). La reprogramación es un `UPDATE` (no admite `ON CONFLICT`) y serializa por profesional con `pg_advisory_xact_lock` dentro de la UoW; `23P01` (y `40P01` como red de seguridad) → 409, nunca 500.
- **Auditoría** (RN-GL-01): acciones `crear`, `reprogramar`, `cancelar` en la misma transacción, con detalle (estado/horario anterior y nuevo, sobreturno, paciente reutilizado, exención de anticipación).
- **Errores nuevos** (`AppError`): `TurnoNoEncontradoError` (404), `TransicionNoPermitidaError` (422), `AnticipacionInsuficienteError` (422).
- **Cola**: `RecordatorioQueue.cancelar(turno_id)` (ZREM con el mismo reintento acotado; nunca lanza).
- **Deuda de spec**: se explicita como requisito que la exclusión de la base es el árbitro del alta concurrente (fix `ON CONFLICT` del commit `ed99dcb`) y se agrega el requisito análogo para la reprogramación concurrente.

## Capabilities

### New Capabilities
- Ninguna (todo es comportamiento del ciclo de vida del turno).

### Modified Capabilities
- `turnos`: alta manual con deduplicación de paciente, sobreturno explícito, reprogramación, cancelación, anticipación mínima según actor, sincronización del recordatorio al mover/cancelar, árbitro de concurrencia en alta y reprogramación; se modifican "Ciclo de estados del turno" (reprogramación de `confirmado` → `reservado`) y "Auditoría append-only" (también `reprogramar`/`cancelar`).

## Impact

- **Código nuevo**: `src/backend/app/application/gestion_turnos.py` (casos de uso `alta_manual_turno`, `reprogramar_turno`, `cancelar_turno` + DTO `TurnoGestionado`), rutas nuevas en `src/backend/app/api/turnos.py`.
- **Código modificado (aditivo)**: `app/infrastructure/repositories_agenda.py` (`excluir_turno_id`, `sobreturno` en `insertar_si_no_solapa`, carga `FOR UPDATE`, advisory lock), `app/application/reservas.py` (`hay_ocupacion` con `excluir_turno_id` opcional; firma y flujo de `reservar_turno` intactos), `app/infrastructure/repositories.py` o nuevo `PacienteRepository` (búsqueda por teléfono), `app/domain/turno_estados.py` (regla de estado tras reprogramar), `app/domain/schemas.py` (`TurnoManualCreate`, `TurnoReprogramar`, `TurnoManualCreado`, `TurnoGestionado`), `app/core/exceptions.py`, `app/infrastructure/jobs.py` (`cancelar`).
- **API**: 3 endpoints nuevos protegidos por `require_secretaria`; `POST /api/turnos` **sin cambios** (sigue creando paciente; ver Open Questions de design).
- **DB**: sin migración (alembic queda en `002`). **Dependencias**: ninguna nueva.
- **Tests**: nuevos de dominio, repositorio, caso de uso, API y concurrencia (`threading.Barrier`); los existentes de C-04/C-04b siguen verdes sin cambiar aserciones.
