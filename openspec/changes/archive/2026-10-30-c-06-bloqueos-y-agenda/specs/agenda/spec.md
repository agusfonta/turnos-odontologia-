# Spec Delta: agenda

## ADDED Requirements

### Requirement: Agenda interna por profesional
El sistema SHALL exponer `GET /api/agenda` para staff autenticado (401 sin token o inválido) con `dia` (fecha local de la clínica, requerida), `vista` (`dia` por defecto, o `semana` = lunes a domingo que contiene `dia`) y `profesional_id`. MUST responder 200 con el profesional, el rango (`desde`, `hasta` inclusivos), los turnos que intersectan el rango y los bloqueos activos que lo intersectan, con instantes ISO 8601 con offset de la clínica.

#### Scenario: Vista día
- **WHEN** una secretaria consulta `vista=dia` de un día con un turno a las 10:00 y otro a las 09:00 del profesional
- **THEN** la respuesta es 200 con `desde = hasta = dia` y los dos turnos ordenados 09:00, 10:00

#### Scenario: Vista semana
- **WHEN** se consulta `vista=semana` con `dia` igual a un miércoles
- **THEN** `desde` es el lunes y `hasta` el domingo de esa semana, e incluye los turnos de los siete días y ninguno de la semana siguiente

#### Scenario: Límites del día en la zona de la clínica
- **WHEN** existe un turno a las 23:30 locales del día anterior y otro a las 00:00 locales del día consultado
- **THEN** la vista día incluye solo el de las 00:00

#### Scenario: Parámetros inválidos
- **WHEN** falta `dia`, `dia` no es una fecha o `vista` no es `dia` ni `semana`
- **THEN** la respuesta es 422

#### Scenario: Profesional inexistente
- **WHEN** `profesional_id` no corresponde a ningún profesional
- **THEN** la respuesta es 404 `profesional_no_encontrado`

### Requirement: Contenido del turno en la agenda
Cada turno de la agenda MUST incluir `id`, `inicio`, `fin`, `estado` (los cinco estados, incluido `cancelado`), `origen` (`online` o `secretaria`), `sobreturno`, el paciente (`id`, `nombre`, `telefono`) y el tratamiento (`id`, `nombre`, o nulo). MUST NOT incluir `token_publico` ni campos no definidos. Cada bloqueo MUST incluir `id`, `desde`, `hasta` y `motivo`; los bloqueos dados de baja MUST NOT aparecer.

#### Scenario: Distingue estados y origen
- **WHEN** el día tiene un turno `reservado` online, uno `confirmado` de secretaria y uno `cancelado`
- **THEN** los tres aparecen con su `estado` y `origen` correspondientes

#### Scenario: Datos de paciente y tratamiento
- **WHEN** un turno tiene tratamiento y otro no
- **THEN** el primero trae `tratamiento` con `id` y `nombre`, el segundo `tratamiento` nulo, y ambos traen el paciente con `id`, `nombre` y `telefono`

#### Scenario: Sin token público
- **WHEN** se consulta cualquier agenda
- **THEN** ningún turno de la respuesta contiene `token_publico`

#### Scenario: Bloqueos del rango
- **WHEN** el día tiene un bloqueo activo de 14:00 a 18:00 y uno dado de baja de 09:00 a 10:00
- **THEN** la respuesta incluye solo el bloqueo activo, con su `motivo`

### Requirement: Aislamiento de agenda por rol
Una secretaria MUST indicar `profesional_id` (422 si falta) y SHALL ver la agenda de cualquier profesional. Un odontólogo MUST ver solo la agenda del profesional vinculado a su usuario: sin `profesional_id` se usa el propio; con el de otro profesional MUST responder 403; sin profesional vinculado MUST responder 403 `sin_profesional_asociado`. La respuesta MUST NOT contener turnos ni bloqueos de otro profesional (US-003 CA-2).

#### Scenario: Odontólogo ve su agenda sin indicar profesional
- **WHEN** un odontólogo vinculado consulta la agenda sin `profesional_id`
- **THEN** la respuesta es 200 con su profesional y solo sus turnos

#### Scenario: Odontólogo pide la agenda de otro
- **WHEN** un odontólogo vinculado consulta con el `profesional_id` de otro profesional
- **THEN** la respuesta es 403 y no incluye datos de ese profesional

#### Scenario: Odontólogo sin profesional vinculado
- **WHEN** un odontólogo sin profesional vinculado consulta la agenda
- **THEN** la respuesta es 403 `sin_profesional_asociado`

#### Scenario: Secretaria sin profesional
- **WHEN** una secretaria consulta la agenda sin `profesional_id`
- **THEN** la respuesta es 422

#### Scenario: Secretaria ve cualquier profesional
- **WHEN** una secretaria consulta la agenda de dos profesionales distintos
- **THEN** cada respuesta contiene solo los turnos y bloqueos del profesional pedido
