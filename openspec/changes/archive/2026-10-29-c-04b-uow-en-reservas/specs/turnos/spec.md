# Spec Delta: turnos

## ADDED Requirements

### Requirement: Reserva atómica
La creación de una reserva SHALL persistir paciente, turno y evento de auditoría `crear` como una única unidad confirmada: o se confirman los tres, o no queda ninguno. Toda reserva que termine en error (404, 409, 422 o 500), incluida una falla al confirmar, MUST NOT dejar filas de paciente, turno ni auditoría de esa solicitud.

#### Scenario: Conflicto detectado por la base no deja residuos
- **WHEN** una reserva es rechazada por la base de datos por superposición con un turno ya confirmado
- **THEN** la respuesta es 409 y no queda ningún paciente, turno ni auditoría de esa solicitud

#### Scenario: Falla al confirmar no deja residuos
- **WHEN** la confirmación de la reserva falla después de haber insertado paciente, turno y auditoría
- **THEN** la respuesta es un error y no queda ningún paciente, turno ni auditoría de esa solicitud, ni se encola recordatorio

#### Scenario: Reserva exitosa confirma todo junto
- **WHEN** una reserva válida responde 201
- **THEN** existen exactamente un paciente, un turno y un evento de auditoría `crear` de esa solicitud, visibles para cualquier otra conexión

### Requirement: Huecos del conflicto leídos tras cerrar la transacción fallida
Cuando una reserva termina en 409 `hueco_ocupado`, la lista `huecos` de la respuesta SHALL calcularse con una lectura nueva, posterior al cierre de la transacción de la reserva rechazada, de modo que refleje el estado confirmado de la agenda (incluido el turno ganador de una carrera) y nunca datos parciales de la reserva rechazada.

#### Scenario: Carrera con huecos actualizados
- **WHEN** dos solicitudes simultáneas reservan el mismo hueco del mismo profesional
- **THEN** una recibe 201, la otra 409 `hueco_ocupado`, y los `huecos` del 409 no incluyen el horario ganado

#### Scenario: Otra violación de integridad no se enmascara
- **WHEN** la base de datos rechaza la reserva por una violación de integridad distinta de la superposición de turnos
- **THEN** la respuesta es 500 y no se devuelve `hueco_ocupado`

## MODIFIED Requirements

### Requirement: Recordatorio encolado sin bloquear la reserva
Tras persistir el turno, el sistema SHALL encolar en Redis un job de recordatorio con el id del turno y el instante objetivo (`inicio` menos 24 h), con reintento acotado. El encolado MUST ocurrir solo después de que la reserva quedó confirmada en la base de datos, nunca antes ni ante una confirmación fallida. Un fallo de Redis MUST NOT impedir ni revertir la reserva y MUST quedar registrado en logs; nunca se envía WhatsApp dentro del request.

#### Scenario: Job encolado
- **WHEN** se crea un turno con Redis disponible
- **THEN** existe un job de recordatorio para ese turno en la cola

#### Scenario: Redis caído
- **WHEN** Redis no responde al encolar
- **THEN** la respuesta igual es 201, el turno queda persistido y se registra una advertencia

#### Scenario: Reserva fallida no encola
- **WHEN** la reserva termina en 409, 404 o 422
- **THEN** no se encola ningún job

#### Scenario: Encolado posterior a la confirmación
- **WHEN** se crea un turno con éxito
- **THEN** en el momento de encolar, el turno ya es visible en la base de datos desde otra conexión

#### Scenario: Confirmación fallida no encola
- **WHEN** la confirmación de la reserva en la base de datos falla
- **THEN** no se encola ningún job
