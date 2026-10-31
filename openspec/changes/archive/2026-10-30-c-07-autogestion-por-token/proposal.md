# Proposal: c-07-autogestion-por-token

> Governance: **MEDIO** (lógica de negocio de turnos: implementar con checkpoints y exponer decisiones). No toca el contrato de `reservar_turno` (CRÍTICO) ni la UoW. Reusa los casos de uso de C-05 (`reprogramar_turno`, `cancelar_turno`) con actor `paciente`; solo agrega `confirmar_turno` y una capa fina de resolución de token. **Sin migración de DB**: `turnos.token_publico` ya es `UNIQUE` (índice) desde la 002 y `auditoria_turno.accion` es texto libre.

## Why

El paciente recibe un `token_publico` al reservar (C-04), pero hoy no puede hacer nada con él: no hay forma de ver, confirmar, cancelar ni reprogramar su turno sin llamar a la clínica. US-005 (cancelar/reprogramar con anticipación), RN-TU-03 (token único para operar sin login) y RN-NO-02 (confirmación 1-clic desde WhatsApp) dependen de esta puerta, y son prerrequisito del portal público (C-09) y de los links de los recordatorios (C-08). C-05 dejó los casos de uso parametrizados por actor justamente para que este change solo agregue la puerta.

## What Changes

- **Consulta por token** `GET /api/turnos/por-token/{token}` (pública): detalle mínimo para gestionar el turno — horario, estado, profesional y tratamiento (id + nombre) y hasta cuándo puede gestionarse; **sin** datos del paciente, sin `id` del turno ni el propio token.
- **Confirmación por token** `POST /api/turnos/por-token/{token}/confirmar` (pública, RN-NO-02): `reservado → confirmado`; reconfirmar un `confirmado` es idempotente (200 sin auditoría nueva); estados terminales → 422; turno ya iniciado → 422.
- **Cancelación por token** `DELETE /api/turnos/por-token/{token}`: mismo caso de uso que la secretaria con actor `paciente` ⇒ exige `CANCEL_MIN_HOURS` hasta el inicio actual (RN-TU-01); quita el recordatorio (`ZREM`) post-commit.
- **Reprogramación por token** `PATCH /api/turnos/por-token/{token}`: body solo `inicio` (sin `sobreturno`, 422 si viene); anticipación sobre el horario actual; revalida el hueco nuevo excluyendo el propio turno; `confirmado` vuelve a `reservado` (DD-07); re-encola el recordatorio post-commit. Mismo árbitro de concurrencia que C-05 (advisory lock + exclusión → 409).
- **Token inválido**: inexistente, malformado o de largo excesivo → el mismo 404 `turno_no_encontrado` en las cuatro rutas, sin datos del turno y sin consultar la base para tokens malformados. El token no se registra en logs de la aplicación.
- **Token estable**: el token no rota al reprogramar ni vence por sí mismo; lo que limita las operaciones es el estado del turno y la anticipación (decisión por defecto, ver Open Questions de design).
- **Confirmación por secretaria** `POST /api/turnos/{turno_id}/confirmar` (solo `secretaria`): mismo caso de uso con actor `secretaria` (decidido en C-05: "confirmar por staff va en C-07").
- **Auditoría** (RN-GL-01): nueva acción `confirmar` (`{estado_anterior}`); cancelar/reprogramar por token auditan con actor `paciente` y `actor_user_id` nulo.

## Capabilities

### New Capabilities
- Ninguna (todo es comportamiento del ciclo de vida del turno; la puerta pública es parte de `turnos`, igual que la reserva pública).

### Modified Capabilities
- `turnos`: consulta, confirmación, cancelación y reprogramación por token; respuesta 404 uniforme sin fuga de datos; confirmación por secretaria; se modifican "Token público de gestión" (estable durante la vida del turno), "Ciclo de estados del turno" (confirmación por API, idempotencia), "Auditoría append-only" (acción `confirmar`, actor paciente), "Anticipación mínima según actor" (la rama paciente pasa a ser alcanzable por HTTP) y "Recordatorio sincronizado tras mover o cancelar" (también por token; confirmar no toca la cola).

`auth` **no** cambia: las rutas por token no usan JWT ni RBAC; el login rate-limit no aplica.

## Impact

- **Código nuevo**: `src/backend/app/application/autogestion.py` (resolución de token, consulta pública, orquestación de las tres operaciones por token sobre los casos de uso de C-05), `src/backend/app/api/autogestion.py` (router `/turnos/por-token`), registro en `app/main.py`.
- **Código modificado (aditivo)**: `app/application/gestion_turnos.py` (`confirmar_turno`), `app/infrastructure/repositories_agenda.py` (`TurnoRepository.id_por_token`, lectura del detalle público), `app/domain/schemas.py` (`TurnoReprogramarPublico`, `TurnoPorTokenOut`, `TurnoPorTokenDetalle`), `app/api/turnos.py` (`POST /{turno_id}/confirmar`), `app/domain/turno_estados.py` solo si hace falta un helper de confirmación idempotente.
- **Sin cambios**: `reservar_turno`, UoW, `reprogramar_turno`/`cancelar_turno` (firma y flujo), rutas de C-04/C-05/C-06.
- **API**: 4 rutas públicas nuevas + 1 de secretaria. **DB**: sin migración (alembic queda en `003`). **Dependencias**: ninguna nueva.
- **Tests**: dominio, repositorio, caso de uso, API (incluida la no-fuga de datos en 404) y concurrencia confirmar↔cancelar y reprogramación por token vs alta.
