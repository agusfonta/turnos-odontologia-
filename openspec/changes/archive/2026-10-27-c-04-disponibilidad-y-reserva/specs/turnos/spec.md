# Spec Delta: turnos

## Purpose

Permite reservar turnos (paciente sin login o secretaria autenticada) garantizando en la base que un odontólogo nunca tenga dos turnos superpuestos, con token público de gestión, ciclo de estados controlado, auditoría append-only y recordatorio encolado de forma asíncrona.

## ADDED Requirements

### Requirement: Reserva pública de turno
El sistema SHALL exponer `POST /api/turnos` sin autenticación con `profesional_id`, `inicio` (datetime con zona explícita), `tratamiento_id` opcional, `paciente_nombre` y `paciente_telefono` (E.164). Ante éxito MUST responder 201 con `id`, `profesional_id`, `tratamiento_id`, `inicio`, `fin`, `estado=reservado`, `origen=online` y `token_publico`.

#### Scenario: Reserva exitosa
- **WHEN** un paciente envía datos válidos para un hueco devuelto por `GET /api/disponibilidad`
- **THEN** la respuesta es 201, el turno queda `reservado` con `origen=online`, `fin = inicio + duración` y se devuelve un `token_publico`

#### Scenario: Paciente creado con datos mínimos
- **WHEN** la reserva pública es exitosa
- **THEN** existe un paciente con el nombre y teléfono enviados asociado al turno

#### Scenario: El cliente no define la duración
- **WHEN** el cuerpo incluye un campo `fin` o cualquier campo no definido
- **THEN** la respuesta es 422

### Requirement: Reserva por secretaria autenticada
El mismo endpoint SHALL aceptar un access token de rol `secretaria`; en ese caso el turno MUST registrarse con `origen=secretaria` y `created_by` = usuario autenticado. Un token inválido o expirado MUST responder 401 y un token de otro rol MUST responder 403, nunca degradar a reserva pública.

#### Scenario: Secretaria reserva
- **WHEN** una secretaria autenticada reserva un hueco válido
- **THEN** la respuesta es 201 con `origen=secretaria` y el turno guarda su usuario como creador

#### Scenario: Token inválido
- **WHEN** se envía `Authorization: Bearer` con un token inválido o expirado
- **THEN** la respuesta es 401 y no se crea ningún turno

#### Scenario: Odontólogo no reserva por este endpoint
- **WHEN** un usuario con rol `odontologo` envía la reserva
- **THEN** la respuesta es 403 y no se crea ningún turno

### Requirement: Validación de la reserva
La reserva MUST validar profesional activo, tratamiento activo si se indica, teléfono E.164, nombre no vacío, zona horaria explícita y que `inicio` sea un hueco real según las reglas de disponibilidad (RN-TU-02).

#### Scenario: Teléfono inválido
- **WHEN** `paciente_telefono` no cumple E.164
- **THEN** la respuesta es 422 con detalle del campo y no se crea turno ni paciente

#### Scenario: Profesional inactivo o inexistente
- **WHEN** `profesional_id` no existe o es de un profesional inactivo
- **THEN** la respuesta es 404 y no se crea nada

#### Scenario: Fecha sin zona horaria
- **WHEN** `inicio` se envía sin offset de zona (naive)
- **THEN** la respuesta es 422

#### Scenario: Inicio fuera de grilla, de horario o en el pasado
- **WHEN** `inicio` no cae en la grilla de huecos, no cabe completo dentro de una franja de atención activa del profesional (incluido un profesional sin horarios) o es pasado
- **THEN** la respuesta es 422 y no se crea nada

### Requirement: Conflicto de hueco ocupado
Si el hueco se superpone con un turno no cancelado o con un bloqueo activo del profesional, incluida una reserva concurrente confirmada entre la consulta y el alta, el sistema MUST responder 409 con `code=hueco_ocupado` y la lista actualizada de huecos del mismo profesional y día (zona de la clínica) para la misma duración.

#### Scenario: Hueco ya ocupado
- **WHEN** se reserva un `inicio` que se superpone con un turno `reservado` existente
- **THEN** la respuesta es 409 con `huecos` que no incluyen el horario ocupado

#### Scenario: Hueco bloqueado
- **WHEN** se reserva un `inicio` dentro de un bloqueo activo
- **THEN** la respuesta es 409 y no se crea turno ni paciente

#### Scenario: Reservas concurrentes
- **WHEN** dos solicitudes simultáneas reservan el mismo hueco del mismo profesional
- **THEN** exactamente una recibe 201 y la otra 409, y existe un único turno en ese horario

### Requirement: Anti-solape garantizado por la base de datos
La base de datos MUST rechazar cualquier par de turnos del mismo profesional con intervalos `[inicio, fin)` superpuestos cuando ninguno está `cancelado` ni marcado como sobreturno, independientemente del código de aplicación (RN-AG-01). MUST cumplirse `fin > inicio`.

#### Scenario: Inserción directa solapada
- **WHEN** se inserta directamente en la tabla un turno que se superpone con otro activo del mismo profesional
- **THEN** la base rechaza la fila con violación de exclusión

#### Scenario: Turnos contiguos permitidos
- **WHEN** un turno termina a las 10:30 y otro del mismo profesional empieza a las 10:30
- **THEN** ambos se aceptan

#### Scenario: Otro profesional mismo horario
- **WHEN** dos profesionales distintos tienen turnos en el mismo horario
- **THEN** ambos se aceptan

### Requirement: Token público de gestión
Cada turno creado SHALL tener un `token_publico` único, no adivinable (al menos 256 bits de entropía) y apto para URL (RN-TU-03), devuelto solo en la respuesta de creación.

#### Scenario: Tokens únicos
- **WHEN** se crean varios turnos
- **THEN** todos tienen `token_publico` distinto y la base rechaza un duplicado

### Requirement: Ciclo de estados del turno
Las transiciones de estado SHALL limitarse a `reservado→confirmado`, `confirmado→atendido`, `confirmado→ausente`, `reservado→cancelado` y `confirmado→cancelado` (RN-TU-04). `cancelado`, `atendido` y `ausente` MUST ser terminales; toda otra transición MUST rechazarse con error de dominio.

#### Scenario: Transición válida
- **WHEN** un turno `reservado` pasa a `confirmado`
- **THEN** la transición se acepta

#### Scenario: Salto prohibido
- **WHEN** un turno `reservado` intenta pasar a `atendido` o a `ausente`
- **THEN** la transición se rechaza

#### Scenario: Estado terminal
- **WHEN** un turno `cancelado` intenta pasar a cualquier otro estado
- **THEN** la transición se rechaza

### Requirement: Auditoría append-only
Toda creación de turno MUST registrar, en la misma transacción, un evento de auditoría con turno, acción `crear`, actor (paciente online o usuario staff), detalle y timestamp (RN-GL-01). La base MUST impedir modificar o borrar registros de auditoría.

#### Scenario: Auditoría en la creación
- **WHEN** se crea un turno por cualquier vía
- **THEN** existe exactamente un registro de auditoría `crear` para ese turno con el actor correspondiente

#### Scenario: Auditoría inmutable
- **WHEN** se intenta un UPDATE o DELETE sobre un registro de auditoría
- **THEN** la base rechaza la operación

#### Scenario: Sin turno no hay auditoría
- **WHEN** la reserva falla con 409, 404 o 422
- **THEN** no queda turno, paciente ni registro de auditoría persistido

### Requirement: Persistencia en zona horaria explícita
Los instantes de turnos y bloqueos SHALL persistirse como `timestamptz` y devolverse en ISO 8601 con el offset de la zona de la clínica (RN-GL-02).

#### Scenario: Entrada con otro offset
- **WHEN** se reserva con `inicio` expresado en UTC que corresponde a un hueco válido
- **THEN** el turno se crea y la respuesta devuelve `inicio` con offset de la zona de la clínica representando el mismo instante

### Requirement: Recordatorio encolado sin bloquear la reserva
Tras persistir el turno, el sistema SHALL encolar en Redis un job de recordatorio con el id del turno y el instante objetivo (`inicio` menos 24 h), con reintento acotado. Un fallo de Redis MUST NOT impedir ni revertir la reserva y MUST quedar registrado en logs; nunca se envía WhatsApp dentro del request.

#### Scenario: Job encolado
- **WHEN** se crea un turno con Redis disponible
- **THEN** existe un job de recordatorio para ese turno en la cola

#### Scenario: Redis caído
- **WHEN** Redis no responde al encolar
- **THEN** la respuesta igual es 201, el turno queda persistido y se registra una advertencia

#### Scenario: Reserva fallida no encola
- **WHEN** la reserva termina en 409, 404 o 422
- **THEN** no se encola ningún job
