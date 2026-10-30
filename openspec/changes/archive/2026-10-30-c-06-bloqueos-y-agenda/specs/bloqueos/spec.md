# Spec Delta: bloqueos

## Purpose
Permite a la secretaria marcar rangos en los que un profesional no atiende (vacaciones, feriados, ausencias) y darlos de baja, garantizando en la base de datos que ningún turno activo quede dentro de un bloqueo activo, también bajo concurrencia (RN-AG-02).

## ADDED Requirements

### Requirement: Alta de bloqueo por secretaria
El sistema SHALL exponer `POST /api/bloqueos`, solo para rol `secretaria` (401 sin token o inválido, 403 otro rol), con `profesional_id`, `desde` y `hasta` con zona explícita y `motivo` obligatorio de 1 a 200 caracteres. Ante éxito MUST responder 201 con `id`, `profesional_id`, `desde`, `hasta` y `motivo`, y el rango `[desde, hasta)` MUST dejar de ofrecerse en la disponibilidad.

#### Scenario: Bloqueo de medio día
- **WHEN** una secretaria crea un bloqueo de 09:00 a 13:00 de un día futuro sin turnos, con motivo "Capacitación"
- **THEN** la respuesta es 201 con los datos del bloqueo y la disponibilidad de ese día empieza a las 13:00

#### Scenario: Sin autenticación o con otro rol
- **WHEN** se llama sin token, con un token inválido o con un token de rol `odontologo`
- **THEN** la respuesta es 401 (sin token o inválido) o 403 (otro rol) y no se crea ningún bloqueo

#### Scenario: Validaciones del bloqueo
- **WHEN** el cuerpo tiene `hasta <= desde`, `desde` anterior al instante actual, un instante sin zona, `motivo` vacío o de más de 200 caracteres, o un campo no definido
- **THEN** la respuesta es 422 y no se crea ningún bloqueo

#### Scenario: Profesional inexistente o inactivo
- **WHEN** `profesional_id` no existe o corresponde a un profesional inactivo
- **THEN** la respuesta es 404 `profesional_no_encontrado` y no se crea ningún bloqueo

#### Scenario: Bloqueos superpuestos entre sí
- **WHEN** ya existe un bloqueo activo de 09:00 a 13:00 y se crea otro de 12:00 a 18:00 del mismo profesional
- **THEN** la respuesta es 201 y la disponibilidad excluye la unión 09:00–18:00

### Requirement: Bloqueo rechazado sobre turnos activos
Un bloqueo MUST NOT crearse si su rango se superpone con algún turno `reservado` o `confirmado` del mismo profesional (intervalos semiabiertos). En ese caso la respuesta MUST ser 409 `bloqueo_con_turnos` con la lista `turnos` de los turnos en conflicto (`id`, `inicio`, `fin`, `estado`), sin datos del paciente ni `token_publico`. Turnos cancelados, atendidos o ausentes MUST NOT impedir el bloqueo.

#### Scenario: Turno reservado dentro del rango
- **WHEN** existe un turno `reservado` de 10:00 a 10:30 y se pide un bloqueo de 09:00 a 13:00 del mismo profesional
- **THEN** la respuesta es 409 `bloqueo_con_turnos` con ese turno en `turnos` y no se crea el bloqueo

#### Scenario: Turno cancelado no impide
- **WHEN** el único turno del rango está `cancelado`
- **THEN** la respuesta es 201

#### Scenario: Turno contiguo no impide
- **WHEN** existe un turno de 08:30 a 09:00 y se pide un bloqueo de 09:00 a 13:00
- **THEN** la respuesta es 201

#### Scenario: Turno de otro profesional no impide
- **WHEN** el turno superpuesto pertenece a otro profesional
- **THEN** la respuesta es 201

### Requirement: Baja lógica de bloqueo
El sistema SHALL exponer `DELETE /api/bloqueos/{bloqueo_id}`, solo para rol `secretaria`, que da de baja el bloqueo de forma lógica (inactivo con fecha de baja, la fila se conserva) y responde 200 con el bloqueo. Un bloqueo inexistente o ya dado de baja MUST responder 404 `bloqueo_no_encontrado`. Tras la baja, el rango MUST volver a la disponibilidad.

#### Scenario: Baja libera el rango
- **WHEN** una secretaria da de baja un bloqueo activo de 09:00 a 13:00
- **THEN** la respuesta es 200, la fila sigue existiendo inactiva con fecha de baja y el hueco de 09:00 vuelve a aparecer en la disponibilidad

#### Scenario: Bloqueo inexistente o ya dado de baja
- **WHEN** se da de baja un id inexistente o un bloqueo ya inactivo
- **THEN** la respuesta es 404 `bloqueo_no_encontrado`

#### Scenario: Sin autenticación, otro rol o id inválido
- **WHEN** se llama sin token, con rol `odontologo` o con un id que no es UUID
- **THEN** la respuesta es 401, 403 o 422 respectivamente y el bloqueo no cambia

### Requirement: Turno y bloqueo nunca se superponen en la base
La base de datos MUST rechazar, independientemente del código de aplicación, un turno `reservado` o `confirmado` cuyo rango se superponga con un bloqueo activo del mismo profesional, y un bloqueo activo cuyo rango se superponga con un turno así, con violación de exclusión (`23P01`). La garantía MUST sostenerse bajo escrituras concurrentes y toda vía de alta o reprogramación MUST responder 409, nunca 500.

#### Scenario: Inserción directa de turno dentro de un bloqueo
- **WHEN** se inserta por SQL un turno `reservado` dentro de un bloqueo activo del mismo profesional
- **THEN** la base rechaza la fila con violación de exclusión

#### Scenario: Inserción directa de bloqueo sobre un turno
- **WHEN** se inserta por SQL un bloqueo activo que pisa un turno `confirmado` del mismo profesional
- **THEN** la base rechaza la fila con violación de exclusión

#### Scenario: Reactivar un bloqueo sobre un turno
- **WHEN** se reactiva por SQL un bloqueo dado de baja cuyo rango ahora pisa un turno `reservado`
- **THEN** la base rechaza la actualización con violación de exclusión

#### Scenario: Cancelar o cerrar un turno no se ve afectado
- **WHEN** un turno existente cambia a `cancelado`, `atendido` o `ausente`
- **THEN** la base acepta el cambio sin consultar bloqueos

#### Scenario: Bloqueo y reserva concurrentes
- **WHEN** una secretaria crea un bloqueo y, en simultáneo, se reserva (pública, alta manual o reprogramación) un turno dentro de ese rango
- **THEN** exactamente una de las dos operaciones tiene éxito, la otra responde 409, ninguna responde 500 y no queda ningún turno activo dentro de un bloqueo activo
