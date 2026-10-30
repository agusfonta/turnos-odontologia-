# Spec Delta: turnos

## ADDED Requirements

### Requirement: Alta manual por secretaria
El sistema SHALL exponer `POST /api/turnos/manual`, solo para rol `secretaria` (401 sin token o inválido, 403 otro rol), con los campos de la reserva más `sobreturno` opcional (default `false`), y validar el hueco igual que la reserva. Ante éxito MUST responder 201 con `id`, `profesional_id`, `paciente_id`, `tratamiento_id`, `inicio`, `fin`, `estado=reservado`, `origen=secretaria`, `sobreturno` y `token_publico`, registrando `created_by` = usuario autenticado.

#### Scenario: Alta manual con paciente nuevo
- **WHEN** una secretaria da de alta un turno válido con un teléfono que no tiene ningún paciente
- **THEN** la respuesta es 201 con `origen=secretaria`, se crea exactamente un paciente con ese nombre y teléfono y el turno guarda a la secretaria como creadora

#### Scenario: Sin autenticación o con otro rol
- **WHEN** se llama al alta manual sin token, con un token inválido o con un token de rol `odontologo`
- **THEN** la respuesta es 401 (sin token o inválido) o 403 (otro rol) y no se crea turno ni paciente

#### Scenario: Validaciones del alta manual
- **WHEN** el alta manual tiene teléfono no E.164, `inicio` sin zona, fuera de grilla/franja o pasado, profesional inexistente o un campo no definido
- **THEN** la respuesta es 422 (o 404 para profesional/tratamiento inexistente o inactivo) y no se crea turno ni paciente

### Requirement: Deduplicación de paciente en el alta manual
El alta manual MUST reutilizar el paciente activo con el mismo teléfono normalizado (el más antiguo si hay varios) y crear uno solo si no existe (DD-06). Un paciente reutilizado MUST NOT modificarse.

#### Scenario: Alta manual reutiliza paciente existente
- **WHEN** una secretaria da de alta un turno con el teléfono de un paciente ya existente, aunque con otro nombre
- **THEN** la respuesta es 201, el turno queda asociado al paciente existente, no se crea ningún paciente nuevo y el nombre del paciente existente no cambia

### Requirement: Sobreturno explícito
Un turno SHALL poder superponerse con otros turnos del mismo profesional solo si la secretaria lo marca con `sobreturno=true` (RN-AG-04); sin la marca, el solape MUST responder 409 `hueco_ocupado`. La marca MUST NOT eximir de bloqueos activos ni de la validación de grilla, franja y futuro, MUST persistirse y auditarse. La reserva pública MUST rechazar el campo con 422.

#### Scenario: Solape sin marca
- **WHEN** una secretaria da de alta un turno que se superpone con un turno `reservado` del mismo profesional sin `sobreturno`
- **THEN** la respuesta es 409 `hueco_ocupado` con `huecos` y no se crea turno ni paciente

#### Scenario: Sobreturno con marca
- **WHEN** una secretaria da de alta el mismo horario con `sobreturno=true`
- **THEN** la respuesta es 201 con `sobreturno=true`, coexisten ambos turnos y la auditoría `crear` registra `sobreturno: true`

#### Scenario: Sobreturno no atraviesa un bloqueo
- **WHEN** una secretaria da de alta con `sobreturno=true` un horario dentro de un bloqueo activo
- **THEN** la respuesta es 409 `hueco_ocupado` y no se crea nada

#### Scenario: Reserva pública no puede pedir sobreturno
- **WHEN** el cuerpo de `POST /api/turnos` incluye `sobreturno`
- **THEN** la respuesta es 422

### Requirement: Reprogramación por secretaria
El sistema SHALL exponer `PATCH /api/turnos/{turno_id}`, solo para rol `secretaria`, con nuevo `inicio` (zona explícita) y `sobreturno` opcional. Se conservan duración, profesional y tratamiento; el nuevo hueco MUST revalidarse como en la reserva sin contar al propio turno. Solo `reservado` o `confirmado` son reprogramables y el resultado MUST quedar `reservado`. Ante éxito MUST responder 200 con el turno (incluidos `paciente_id`, `estado` y `sobreturno`), sin `token_publico`.

#### Scenario: Reprogramación a un hueco libre
- **WHEN** una secretaria reprograma un turno `reservado` a un hueco libre del mismo profesional
- **THEN** la respuesta es 200 con el nuevo `inicio`, `fin = inicio + duración original` y el horario anterior queda disponible

#### Scenario: Reprogramación que pisa su propio horario
- **WHEN** una secretaria reprograma un turno de 10:00–11:00 a las 10:30 y ningún otro turno ocupa 10:30–11:30
- **THEN** la respuesta es 200 (el propio turno no cuenta como ocupación)

#### Scenario: Reprogramación a un hueco ocupado
- **WHEN** el nuevo horario se superpone con otro turno no cancelado o un bloqueo activo y no hay marca de sobreturno
- **THEN** la respuesta es 409 `hueco_ocupado` con `huecos` del nuevo día y el turno conserva su horario y estado

#### Scenario: Turno confirmado vuelve a reservado
- **WHEN** una secretaria reprograma un turno `confirmado`
- **THEN** la respuesta es 200 con `estado=reservado`

#### Scenario: Estado terminal o turno inexistente
- **WHEN** se reprograma un turno `cancelado`, `atendido` o `ausente`, o un `turno_id` que no existe
- **THEN** la respuesta es 422 `transicion_no_permitida` o 404 `turno_no_encontrado` respectivamente, y no se modifica ni audita nada

#### Scenario: Nuevo inicio inválido
- **WHEN** el nuevo `inicio` está fuera de grilla, fuera de franja, en el pasado o sin zona
- **THEN** la respuesta es 422 y el turno no cambia

### Requirement: Cancelación por secretaria
El sistema SHALL exponer `DELETE /api/turnos/{turno_id}`, accesible solo con rol `secretaria`, que pasa el turno a `cancelado` (baja lógica: la fila se conserva y el horario se libera). Solo los turnos `reservado` o `confirmado` MUST poder cancelarse. Ante éxito MUST responder 200 con el turno en `estado=cancelado` (mismo cuerpo que la reprogramación).

#### Scenario: Cancelación exitosa libera el hueco
- **WHEN** una secretaria cancela un turno `reservado` o `confirmado`
- **THEN** la respuesta es 200 con `estado=cancelado`, la fila sigue existiendo y el horario vuelve a aparecer en la disponibilidad

#### Scenario: Cancelar un turno terminal
- **WHEN** se cancela un turno ya `cancelado`, `atendido` o `ausente`
- **THEN** la respuesta es 422 `transicion_no_permitida` y no se audita nada

#### Scenario: Cancelar sin permiso
- **WHEN** se cancela sin token o con rol `odontologo`
- **THEN** la respuesta es 401 o 403 y el turno no cambia

### Requirement: Anticipación mínima según actor
Cancelar o reprogramar como paciente MUST requerir al menos `CANCEL_MIN_HOURS` horas (default 24) hasta el `inicio` actual (RN-TU-01); si no, 422 `anticipacion_insuficiente`. La secretaria MUST estar exenta (DD-05) pero MUST NOT operar sobre un turno ya iniciado (mismo 422), y su operación dentro de la ventana MUST auditar la exención.

#### Scenario: Secretaria dentro de la ventana
- **WHEN** una secretaria cancela o reprograma un turno que empieza en menos de `CANCEL_MIN_HOURS` horas
- **THEN** la operación se acepta y la auditoría registra `exento_anticipacion: true`

#### Scenario: Turno ya iniciado
- **WHEN** una secretaria cancela o reprograma un turno cuyo `inicio` es anterior al instante actual
- **THEN** la respuesta es 422 `anticipacion_insuficiente` y el turno no cambia

#### Scenario: Paciente dentro de la ventana
- **WHEN** el caso de uso de cancelación o reprogramación se invoca con actor paciente para un turno que empieza en menos de `CANCEL_MIN_HOURS` horas
- **THEN** se rechaza con `anticipacion_insuficiente` (422) y no se modifica ni audita nada

#### Scenario: Anticipación configurable
- **WHEN** `CANCEL_MIN_HOURS` vale 3 y el paciente cancela un turno que empieza en 4 horas
- **THEN** la cancelación se acepta

### Requirement: Recordatorio sincronizado tras mover o cancelar
Tras una reprogramación confirmada en la base, el sistema SHALL re-encolar el recordatorio del turno con el nuevo instante objetivo (`inicio` nuevo menos 24 h); tras una cancelación confirmada SHALL quitarlo de la cola. Ambos efectos MUST ocurrir solo después del commit, nunca ante una operación fallida, con reintento acotado; un fallo de Redis MUST NOT impedir ni revertir la operación y MUST quedar registrado en logs. Nunca se envía WhatsApp dentro del request.

#### Scenario: Reprogramación re-encola
- **WHEN** una secretaria reprograma un turno con Redis disponible
- **THEN** la cola tiene un único job para ese turno con el instante objetivo del nuevo `inicio`

#### Scenario: Cancelación desencola
- **WHEN** una secretaria cancela un turno que tenía job de recordatorio
- **THEN** la cola ya no tiene job para ese turno

#### Scenario: Operación fallida no toca la cola
- **WHEN** la reprogramación o la cancelación termina en 404, 409 o 422
- **THEN** la cola queda igual que antes

#### Scenario: Redis caído al mover o cancelar
- **WHEN** Redis no responde al re-encolar o desencolar
- **THEN** la respuesta igual es 200, el cambio queda persistido y se registra una advertencia

### Requirement: La exclusión de la base es el árbitro del alta concurrente
Toda alta de turno (reserva pública, de secretaria o alta manual) SHALL delegar la decisión de superposición en la exclusión `ex_turnos_sin_solape` mediante una inserción condicional (`INSERT … ON CONFLICT ON CONSTRAINT ex_turnos_sin_solape DO NOTHING`); una inserción que no devuelve fila MUST traducirse en 409 `hueco_ocupado`. Bajo concurrencia MUST NOT producirse errores 500 ni deadlocks.

#### Scenario: N altas simultáneas del mismo hueco
- **WHEN** N (N ≥ 2) solicitudes simultáneas dan de alta el mismo hueco del mismo profesional
- **THEN** exactamente una recibe 201, las N-1 restantes reciben 409 `hueco_ocupado`, ninguna recibe 500 y existe un único turno en ese horario

#### Scenario: Inserción condicional sin fila no deja residuos
- **WHEN** la inserción condicional del turno no devuelve fila porque el hueco ya fue tomado
- **THEN** no queda ningún paciente nuevo, turno ni auditoría de esa solicitud

### Requirement: Reprogramación concurrente sin deadlock
Las reprogramaciones y altas concurrentes que compiten por el mismo hueco del mismo profesional SHALL resolverse con exactamente un ganador; los perdedores MUST recibir 409 `hueco_ocupado`, nunca 500 ni deadlock, y la agenda MUST quedar sin superposiciones entre turnos no cancelados sin marca de sobreturno.

#### Scenario: Dos reprogramaciones simultáneas al mismo hueco
- **WHEN** dos secretarias reprograman simultáneamente dos turnos distintos del mismo profesional al mismo horario libre
- **THEN** una recibe 200, la otra 409 `hueco_ocupado`, ninguna 500, y el perdedor conserva su horario original

#### Scenario: Reprogramación y alta simultáneas al mismo hueco
- **WHEN** una reprogramación y una alta (pública o manual) apuntan simultáneamente al mismo horario libre del mismo profesional
- **THEN** exactamente una tiene éxito, la otra recibe 409 `hueco_ocupado` y ninguna recibe 500

#### Scenario: Reprogramaciones cruzadas
- **WHEN** dos turnos del mismo profesional se reprograman simultáneamente cada uno al horario del otro
- **THEN** ninguna respuesta es 500, a lo sumo una tiene éxito y la agenda queda sin superposiciones

## MODIFIED Requirements

### Requirement: Ciclo de estados del turno
Las transiciones de estado SHALL limitarse a `reservado→confirmado`, `confirmado→atendido`, `confirmado→ausente`, `reservado→cancelado` y `confirmado→cancelado` (RN-TU-04). `cancelado`, `atendido` y `ausente` MUST ser terminales; toda otra transición MUST rechazarse con error de dominio. Como única excepción, la reprogramación de un turno `reservado` o `confirmado` MUST dejarlo en `reservado` (DD-07); la reprogramación de un turno terminal MUST rechazarse. Por la API, una transición rechazada MUST responder 422 `transicion_no_permitida`.

#### Scenario: Transición válida
- **WHEN** un turno `reservado` pasa a `confirmado`
- **THEN** la transición se acepta

#### Scenario: Salto prohibido
- **WHEN** un turno `reservado` intenta pasar a `atendido` o a `ausente`
- **THEN** la transición se rechaza

#### Scenario: Estado terminal
- **WHEN** un turno `cancelado` intenta pasar a cualquier otro estado
- **THEN** la transición se rechaza

#### Scenario: Confirmado no vuelve a reservado salvo por reprogramación
- **WHEN** un turno `confirmado` intenta pasar a `reservado` como transición directa
- **THEN** la transición se rechaza, mientras que reprogramarlo lo deja en `reservado`

### Requirement: Auditoría append-only
Toda creación, reprogramación y cancelación de turno MUST registrar, en la misma transacción, un evento de auditoría con turno, acción (`crear`, `reprogramar` o `cancelar`), actor (paciente online o usuario staff), detalle y timestamp (RN-GL-01). El detalle de `reprogramar` MUST incluir horario y estado anteriores y nuevos; el de `cancelar`, el estado anterior; ambos, si hubo exención de anticipación; el de `crear` por alta manual, el `sobreturno` y si el paciente fue reutilizado. La base MUST impedir modificar o borrar registros de auditoría.

#### Scenario: Auditoría en la creación
- **WHEN** se crea un turno por cualquier vía
- **THEN** existe exactamente un registro de auditoría `crear` para ese turno con el actor correspondiente

#### Scenario: Auditoría en reprogramación y cancelación
- **WHEN** una secretaria reprograma o cancela un turno con éxito
- **THEN** existe exactamente un registro nuevo `reprogramar` o `cancelar` para ese turno, con actor `secretaria`, su usuario y el detalle correspondiente

#### Scenario: Auditoría inmutable
- **WHEN** se intenta un UPDATE o DELETE sobre un registro de auditoría
- **THEN** la base rechaza la operación

#### Scenario: Sin turno no hay auditoría
- **WHEN** la reserva falla con 409, 404 o 422
- **THEN** no queda turno, paciente ni registro de auditoría persistido

#### Scenario: Operación fallida no audita
- **WHEN** una reprogramación o cancelación termina en 404, 409, 422 o 500
- **THEN** no queda ningún registro de auditoría nuevo para ese turno
