# Spec Delta: turnos

## ADDED Requirements

### Requirement: Consulta del turno por token
El sistema SHALL exponer `GET /api/turnos/por-token/{token}`, pública (sin JWT), que responde 200 con el detalle mínimo para gestionar el turno: horario, estado, profesional y tratamiento (id y nombre) y `gestionable_hasta` (= `inicio` menos `CANCEL_MIN_HOURS`), para cualquier estado. La respuesta MUST NOT incluir datos del paciente, el `id` del turno, el token, el origen ni la marca de sobreturno.

#### Scenario: Turno sin tratamiento
- **WHEN** se consulta por token un turno sin tratamiento
- **THEN** `tratamiento_id` y `tratamiento_nombre` son nulos y `inicio`, `fin` y `gestionable_hasta` llevan el offset de la zona de la clínica

#### Scenario: Consulta con token válido
- **WHEN** se consulta un turno `reservado` con su token
- **THEN** la respuesta es 200 con horario, estado, profesional, tratamiento y `gestionable_hasta`, y el cuerpo no contiene `paciente_id`, el nombre ni el teléfono del paciente, `id`, `token_publico`, `origen` ni `sobreturno`

#### Scenario: Consulta de un turno cancelado
- **WHEN** se consulta con su token un turno `cancelado`
- **THEN** la respuesta es 200 con `estado=cancelado`

#### Scenario: Consulta no modifica nada
- **WHEN** se consulta un turno por token
- **THEN** no se crea ningún registro de auditoría y la cola de recordatorios no cambia

### Requirement: Token inválido sin fuga de datos
Todas las rutas por token MUST responder exactamente el mismo 404 `turno_no_encontrado` (mismo cuerpo) cuando el token no corresponde a ningún turno, tiene caracteres fuera del alfabeto URL-safe o supera 64 caracteres; la respuesta MUST NOT revelar si el turno existe ni ningún dato suyo, y MUST NOT modificar turnos, auditoría ni la cola. Un token malformado MUST rechazarse sin consultar la base. El token MUST NOT escribirse en los logs de la aplicación.

#### Scenario: Token inexistente
- **WHEN** se consulta, confirma, cancela o reprograma con un token bien formado que no corresponde a ningún turno
- **THEN** la respuesta es 404 `turno_no_encontrado` con el mismo cuerpo en las cuatro rutas y no cambia nada en la base ni en la cola

#### Scenario: Token malformado
- **WHEN** el token contiene caracteres no URL-safe o mide más de 64 caracteres
- **THEN** la respuesta es el mismo 404 `turno_no_encontrado` (no 422) y no se ejecuta ninguna consulta de turnos

#### Scenario: El 404 no distingue tokens
- **WHEN** se comparan las respuestas para un token inexistente y para un token malformado
- **THEN** el código de estado y el cuerpo son idénticos

### Requirement: Confirmación por token
El sistema SHALL exponer `POST /api/turnos/por-token/{token}/confirmar`, pública (RN-NO-02), que pasa un turno `reservado` a `confirmado` y responde 200 con el cuerpo de la consulta por token (sin nombres). Reconfirmar un `confirmado` MUST ser un no-op exitoso. Un turno terminal MUST responder 422 `transicion_no_permitida` y uno ya iniciado 422 `anticipacion_insuficiente`. La confirmación MUST NOT exigir la anticipación mínima ni revalidar el hueco.

#### Scenario: Confirmación exitosa
- **WHEN** el paciente confirma con su token un turno `reservado` futuro
- **THEN** la respuesta es 200 con `estado=confirmado` y existe exactamente un registro de auditoría `confirmar` con actor `paciente` y sin usuario

#### Scenario: Confirmación repetida
- **WHEN** el paciente confirma un turno que ya está `confirmado`
- **THEN** la respuesta es 200 con `estado=confirmado` y no se agrega ningún registro de auditoría

#### Scenario: Confirmar un turno cancelado
- **WHEN** se confirma con su token un turno `cancelado`, `atendido` o `ausente`
- **THEN** la respuesta es 422 `transicion_no_permitida`, el estado no cambia y no se audita nada

#### Scenario: Confirmar dentro de la ventana de anticipación
- **WHEN** el paciente confirma un turno `reservado` que empieza en menos de `CANCEL_MIN_HOURS` horas
- **THEN** la confirmación se acepta (200)

#### Scenario: Confirmar un turno ya iniciado
- **WHEN** el paciente confirma un turno `reservado` cuyo `inicio` es anterior al instante actual
- **THEN** la respuesta es 422 `anticipacion_insuficiente` y el turno no cambia

### Requirement: Cancelación por token
El sistema SHALL exponer `DELETE /api/turnos/por-token/{token}`, pública, que cancela el turno como lo hace la secretaria pero con actor `paciente`: solo `reservado` o `confirmado`, sujeto a la anticipación mínima del paciente (RN-TU-01). Ante éxito MUST responder 200 con el mismo cuerpo que la consulta por token y `estado=cancelado`; el horario vuelve a estar disponible.

#### Scenario: Cancelación por token con anticipación suficiente
- **WHEN** el paciente cancela con su token un turno que empieza en más de `CANCEL_MIN_HOURS` horas
- **THEN** la respuesta es 200 con `estado=cancelado`, el horario vuelve a aparecer en la disponibilidad y existe un registro de auditoría `cancelar` con actor `paciente`

#### Scenario: Cancelación por token fuera de plazo
- **WHEN** el paciente cancela un turno que empieza en menos de `CANCEL_MIN_HOURS` horas
- **THEN** la respuesta es 422 `anticipacion_insuficiente` con `min_horas`, el turno no cambia y no se audita nada

#### Scenario: Cancelación por token de un turno terminal
- **WHEN** el paciente cancela con su token un turno ya `cancelado`
- **THEN** la respuesta es 422 `transicion_no_permitida`

### Requirement: Reprogramación por token
El sistema SHALL exponer `PATCH /api/turnos/por-token/{token}`, pública, cuyo cuerpo solo admite `inicio` (zona explícita; otro campo → 422). Se aplican las reglas de la reprogramación por secretaria más la anticipación mínima del paciente sobre el `inicio` actual; al nuevo `inicio` solo se le exige ser un hueco válido y futuro. Ante éxito MUST responder 200 con el cuerpo de la consulta por token (sin nombres).

#### Scenario: Reprogramación por token a un hueco libre
- **WHEN** el paciente reprograma con su token un turno `confirmado` que empieza en más de `CANCEL_MIN_HOURS` horas a un hueco libre
- **THEN** la respuesta es 200 con el nuevo `inicio`, `estado=reservado`, el horario anterior queda disponible y existe un registro de auditoría `reprogramar` con actor `paciente`

#### Scenario: Reprogramación por token fuera de plazo
- **WHEN** el turno actual empieza en menos de `CANCEL_MIN_HOURS` horas
- **THEN** la respuesta es 422 `anticipacion_insuficiente` y el turno conserva horario y estado

#### Scenario: Reprogramación por token a un hueco ocupado
- **WHEN** el nuevo horario se superpone con otro turno no cancelado o con un bloqueo activo
- **THEN** la respuesta es 409 `hueco_ocupado` con `huecos` y el turno no cambia

#### Scenario: El paciente no puede pedir sobreturno
- **WHEN** el cuerpo de la reprogramación por token incluye `sobreturno`
- **THEN** la respuesta es 422 y el turno no cambia

#### Scenario: Reprogramación por token concurrente
- **WHEN** un paciente reprograma por token al mismo hueco que otra reserva o reprogramación simultánea
- **THEN** exactamente una operación tiene éxito, la otra recibe 409 `hueco_ocupado` y ninguna responde 500

### Requirement: Confirmación por secretaria
El sistema SHALL exponer `POST /api/turnos/{turno_id}/confirmar`, solo para rol `secretaria` (401 sin token o inválido, 403 otro rol), con las mismas reglas que la confirmación por token (idempotente sobre `confirmado`, 422 para terminales o turnos ya iniciados, 404 si no existe). Ante éxito MUST responder 200 con el mismo cuerpo que la reprogramación por secretaria y auditar `confirmar` con actor `secretaria` y su usuario.

#### Scenario: Secretaria confirma un turno
- **WHEN** una secretaria confirma un turno `reservado` futuro
- **THEN** la respuesta es 200 con `estado=confirmado` y la auditoría `confirmar` registra actor `secretaria` y su usuario

#### Scenario: Confirmar sin permiso
- **WHEN** se llama sin token, con token inválido o con rol `odontologo`
- **THEN** la respuesta es 401 o 403 y el turno no cambia

### Requirement: Confirmación concurrente con cancelación
Una confirmación y una cancelación simultáneas del mismo turno MUST serializarse: ninguna MUST responder 500 y el estado final MUST ser coherente con el orden en que se aplicaron (`cancelado` si la cancelación fue última; si la confirmación llegó después de la cancelación, 422 `transicion_no_permitida`).

#### Scenario: Confirmar y cancelar a la vez
- **WHEN** el mismo turno `reservado` recibe una confirmación y una cancelación por token simultáneas
- **THEN** ninguna respuesta es 500, el estado final es `cancelado` y la cantidad de auditorías nuevas coincide con las operaciones exitosas

## MODIFIED Requirements

### Requirement: Token público de gestión
Cada turno creado SHALL tener un `token_publico` único, no adivinable (al menos 256 bits de entropía) y apto para URL (RN-TU-03), devuelto solo en la respuesta de creación. El token MUST permanecer igual durante toda la vida del turno (no rota al reprogramar ni al confirmar) y no tiene vencimiento propio: las operaciones que habilita quedan limitadas por el estado del turno y la anticipación mínima. Sin un token válido no hay operación pública sobre un turno existente.

#### Scenario: Tokens únicos
- **WHEN** se crean varios turnos
- **THEN** todos tienen `token_publico` distinto y la base rechaza un duplicado

#### Scenario: Token estable tras reprogramar
- **WHEN** un turno se reprograma (por token o por secretaria) o se confirma
- **THEN** su token sigue siendo el mismo y la consulta por ese token devuelve el horario y estado nuevos

### Requirement: Ciclo de estados del turno
Las transiciones de estado SHALL limitarse a `reservado→confirmado`, `confirmado→atendido`, `confirmado→ausente`, `reservado→cancelado` y `confirmado→cancelado` (RN-TU-04). `cancelado`, `atendido` y `ausente` MUST ser terminales; toda otra transición MUST rechazarse con error de dominio. Como única excepción, la reprogramación de un turno `reservado` o `confirmado` MUST dejarlo en `reservado` (DD-07); la reprogramación de un turno terminal MUST rechazarse. La confirmación por API de un turno ya `confirmado` MUST tratarse como no-op exitoso (sin transición ni auditoría). Por la API, una transición rechazada MUST responder 422 `transicion_no_permitida`.

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

#### Scenario: Reconfirmar es un no-op
- **WHEN** se confirma por API un turno ya `confirmado`
- **THEN** la operación es exitosa, el estado sigue `confirmado` y no se registra auditoría

### Requirement: Auditoría append-only
Toda creación, confirmación, reprogramación y cancelación de turno MUST registrar, en la misma transacción, un evento de auditoría con turno, acción (`crear`, `confirmar`, `reprogramar` o `cancelar`), actor (paciente por la puerta pública o por token, o usuario staff), detalle y timestamp (RN-GL-01). Las operaciones por token MUST auditar con actor `paciente` y sin usuario. El detalle de `reprogramar` MUST incluir horario y estado anteriores y nuevos; el de `cancelar` y el de `confirmar`, el estado anterior; `reprogramar` y `cancelar`, si hubo exención de anticipación; el de `crear` por alta manual, el `sobreturno` y si el paciente fue reutilizado. La base MUST impedir modificar o borrar registros de auditoría.

#### Scenario: Auditoría en la creación
- **WHEN** se crea un turno por cualquier vía
- **THEN** existe exactamente un registro de auditoría `crear` para ese turno con el actor correspondiente

#### Scenario: Auditoría en reprogramación y cancelación
- **WHEN** una secretaria reprograma o cancela un turno con éxito
- **THEN** existe exactamente un registro nuevo `reprogramar` o `cancelar` para ese turno, con actor `secretaria`, su usuario y el detalle correspondiente

#### Scenario: Auditoría de operaciones por token
- **WHEN** el paciente confirma, reprograma o cancela con éxito por token
- **THEN** existe exactamente un registro nuevo `confirmar`, `reprogramar` o `cancelar` para ese turno, con actor `paciente`, `actor_user_id` nulo y el detalle correspondiente

#### Scenario: Auditoría inmutable
- **WHEN** se intenta un UPDATE o DELETE sobre un registro de auditoría
- **THEN** la base rechaza la operación

#### Scenario: Sin turno no hay auditoría
- **WHEN** la reserva falla con 409, 404 o 422
- **THEN** no queda turno, paciente ni registro de auditoría persistido

#### Scenario: Operación fallida no audita
- **WHEN** una confirmación, reprogramación o cancelación termina en 404, 409, 422 o 500
- **THEN** no queda ningún registro de auditoría nuevo para ese turno

### Requirement: Anticipación mínima según actor
Cancelar o reprogramar como paciente (puerta por token) MUST requerir al menos `CANCEL_MIN_HOURS` horas (default 24) hasta el `inicio` actual (RN-TU-01); si no, 422 `anticipacion_insuficiente` con `min_horas`. La secretaria MUST estar exenta (DD-05) pero MUST NOT operar sobre un turno ya iniciado (mismo 422), y su operación dentro de la ventana MUST auditar la exención. La confirmación no está sujeta a la anticipación mínima, pero ningún actor MUST poder confirmar un turno ya iniciado (mismo 422).

#### Scenario: Secretaria dentro de la ventana
- **WHEN** una secretaria cancela o reprograma un turno que empieza en menos de `CANCEL_MIN_HOURS` horas
- **THEN** la operación se acepta y la auditoría registra `exento_anticipacion: true`

#### Scenario: Turno ya iniciado
- **WHEN** una secretaria cancela o reprograma un turno cuyo `inicio` es anterior al instante actual
- **THEN** la respuesta es 422 `anticipacion_insuficiente` y el turno no cambia

#### Scenario: Paciente dentro de la ventana
- **WHEN** el paciente cancela o reprograma por token un turno que empieza en menos de `CANCEL_MIN_HOURS` horas
- **THEN** la respuesta es 422 `anticipacion_insuficiente` y no se modifica ni audita nada

#### Scenario: Borde exacto de la ventana
- **WHEN** el paciente cancela por token un turno que empieza en exactamente `CANCEL_MIN_HOURS` horas
- **THEN** la cancelación se acepta

#### Scenario: Anticipación configurable
- **WHEN** `CANCEL_MIN_HOURS` vale 3 y el paciente cancela por token un turno que empieza en 4 horas
- **THEN** la cancelación se acepta

### Requirement: Recordatorio sincronizado tras mover o cancelar
Tras una reprogramación confirmada en la base, por secretaria o por token, el sistema SHALL re-encolar el recordatorio del turno con el nuevo instante objetivo (`inicio` nuevo menos 24 h); tras una cancelación confirmada, por secretaria o por token, SHALL quitarlo de la cola. Ambos efectos MUST ocurrir solo después del commit, nunca ante una operación fallida, con reintento acotado; un fallo de Redis MUST NOT impedir ni revertir la operación y MUST quedar registrado en logs. La confirmación y la consulta MUST NOT tocar la cola. Nunca se envía WhatsApp dentro del request.

#### Scenario: Reprogramación re-encola
- **WHEN** una secretaria o el paciente por token reprograma un turno con Redis disponible
- **THEN** la cola tiene un único job para ese turno con el instante objetivo del nuevo `inicio`

#### Scenario: Cancelación desencola
- **WHEN** una secretaria o el paciente por token cancela un turno que tenía job de recordatorio
- **THEN** la cola ya no tiene job para ese turno

#### Scenario: Confirmación no toca la cola
- **WHEN** se confirma un turno que tenía job de recordatorio
- **THEN** la cola conserva ese job con el mismo instante objetivo

#### Scenario: Operación fallida no toca la cola
- **WHEN** la reprogramación o la cancelación termina en 404, 409 o 422
- **THEN** la cola queda igual que antes

#### Scenario: Redis caído al mover o cancelar
- **WHEN** Redis no responde al re-encolar o desencolar
- **THEN** la respuesta igual es 200, el cambio queda persistido y se registra una advertencia
