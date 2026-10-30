# agenda Specification

## Purpose
Expone al paciente y al staff qué odontólogos atienden, qué tratamientos se ofrecen y en qué horarios libres se puede reservar, calculando huecos reales a partir de los horarios de atención de cada profesional, la duración del tratamiento, los turnos que ocupan agenda y los bloqueos.

## Requirements

### Requirement: Listado público de profesionales activos
El sistema SHALL exponer `GET /api/profesionales` sin autenticación, devolviendo solo profesionales activos con `id`, `nombre` y `especialidad`, ordenados por nombre. MUST NOT exponer matrícula ni datos de auditoría.

#### Scenario: Solo activos
- **WHEN** existen un profesional activo y uno inactivo y se llama a `GET /api/profesionales`
- **THEN** la respuesta es 200 y contiene únicamente el activo, con `id`, `nombre` y `especialidad`

#### Scenario: Sin profesionales activos
- **WHEN** no hay profesionales activos
- **THEN** la respuesta es 200 con una lista vacía

### Requirement: Listado público de tratamientos activos
El sistema SHALL exponer `GET /api/tratamientos` sin autenticación y de solo lectura, devolviendo únicamente tratamientos activos con exactamente `id`, `nombre` y `duracion_min`, ordenados por nombre. MUST NOT exponer tratamientos inactivos o dados de baja ni campos de auditoría.

#### Scenario: Solo activos
- **WHEN** existen un tratamiento activo y uno inactivo y se llama a `GET /api/tratamientos`
- **THEN** la respuesta es 200 y contiene únicamente el activo, con `id`, `nombre` y `duracion_min`

#### Scenario: Tratamiento dado de baja excluido
- **WHEN** un tratamiento fue dado de baja lógica (inactivo con fecha de baja)
- **THEN** no aparece en la respuesta

#### Scenario: Sin campos extra
- **WHEN** se consulta `GET /api/tratamientos`
- **THEN** ningún elemento contiene campos distintos de `id`, `nombre` y `duracion_min`

#### Scenario: Sin tratamientos activos
- **WHEN** no hay tratamientos activos
- **THEN** la respuesta es 200 con una lista vacía

### Requirement: Consulta de disponibilidad
El sistema SHALL exponer `GET /api/disponibilidad` sin autenticación con `profesional_id` (requerido), `desde` y `hasta` (fechas calendario en la zona de la clínica, inclusivas, requeridas) y `tratamiento_id` (opcional), devolviendo la lista ordenada de huecos `{inicio, fin}` en ISO 8601 con offset de la clínica.

#### Scenario: Huecos de un día libre
- **WHEN** se consulta un día futuro sin turnos ni bloqueos en el que el profesional tiene una franja 09:00–18:00, `slot_default_min=30` y sin tratamiento
- **THEN** se devuelven 18 huecos de 30 minutos desde 09:00 hasta 17:30 con offset `-03:00`

#### Scenario: Profesional inexistente o inactivo
- **WHEN** `profesional_id` no existe o corresponde a un profesional inactivo
- **THEN** la respuesta es 404

#### Scenario: Tratamiento inexistente o inactivo
- **WHEN** `tratamiento_id` no existe o corresponde a un tratamiento inactivo
- **THEN** la respuesta es 404

#### Scenario: Rango inválido
- **WHEN** `hasta` es anterior a `desde` o el rango supera 31 días
- **THEN** la respuesta es 422

### Requirement: Duración del hueco según tratamiento o slot
Cada hueco SHALL durar `duracion_min` del tratamiento indicado o, sin tratamiento, `slot_default_min` del profesional (RN-AG-03). Los inicios posibles MUST caer en una grilla que arranca en la `hora_inicio` de cada franja con paso `slot_default_min`, y el hueco completo MUST caber dentro de una sola franja.

#### Scenario: Tratamiento más largo que el slot
- **WHEN** se consulta con un tratamiento de 60 minutos, `slot_default_min=30` y una franja 09:00–18:00 sin ocupación
- **THEN** los huecos empiezan cada 30 minutos (09:00, 09:30, …) y el último empieza a las 17:00 y termina a las 18:00

#### Scenario: Sin tratamiento usa el slot del profesional
- **WHEN** se consulta sin `tratamiento_id` para un profesional con `slot_default_min=20`
- **THEN** cada hueco dura 20 minutos

### Requirement: Horarios de atención por profesional
Cada profesional SHALL tener cero o más franjas de atención activas, cada una con día de la semana (0=lunes … 6=domingo), hora de inicio y hora de fin, interpretadas en la zona horaria de la clínica (RN-GL-02). Un mismo día MAY tener varias franjas. Fuera de las franjas activas del profesional MUST NOT ofrecerse ningún hueco.

#### Scenario: Franjas múltiples en el mismo día
- **WHEN** el profesional tiene franjas 09:00–13:00 y 15:00–19:00 el lunes, `slot_default_min=30` y se consulta un lunes futuro libre
- **THEN** se devuelven huecos de 09:00 a 12:30 y de 15:00 a 18:30, y ninguno entre 13:00 y 15:00

#### Scenario: El hueco debe caber en una sola franja
- **WHEN** las franjas son 09:00–13:00 y 15:00–19:00 y se consulta con un tratamiento de 60 minutos
- **THEN** el último hueco de la mañana empieza a las 12:00 y no se ofrece ningún hueco que empiece a las 12:30 ni que cruce de una franja a otra

#### Scenario: Día sin franja
- **WHEN** se consulta un día de la semana en el que el profesional no tiene franjas activas
- **THEN** no se devuelven huecos para ese día

#### Scenario: Profesional sin horarios
- **WHEN** el profesional activo no tiene ninguna franja activa
- **THEN** la respuesta de disponibilidad es 200 con una lista vacía

#### Scenario: Franja inactiva no genera huecos
- **WHEN** una franja del profesional fue dada de baja lógica
- **THEN** no se generan huecos a partir de ella

#### Scenario: Huecos pasados excluidos
- **WHEN** se consulta un rango que incluye el día actual
- **THEN** no se devuelve ningún hueco cuyo inicio sea anterior o igual al instante actual

### Requirement: Integridad de franjas en la base de datos
La base de datos MUST rechazar franjas con `dia_semana` fuera de 0–6, con `hora_fin <= hora_inicio`, y franjas activas superpuestas del mismo profesional en el mismo día, independientemente del código de aplicación. Franjas contiguas MUST aceptarse.

#### Scenario: Franjas solapadas rechazadas
- **WHEN** se inserta para el mismo profesional y día una franja activa 12:00–14:00 existiendo otra activa 09:00–13:00
- **THEN** la base rechaza la fila con violación de exclusión

#### Scenario: Franjas contiguas permitidas
- **WHEN** existen franjas 09:00–13:00 y 13:00–17:00 del mismo profesional y día
- **THEN** ambas se aceptan

#### Scenario: Valores inválidos
- **WHEN** se inserta una franja con `dia_semana=7` o con `hora_fin` menor o igual a `hora_inicio`
- **THEN** la base rechaza la fila con violación de CHECK

#### Scenario: Otro profesional o franja inactiva
- **WHEN** la franja superpuesta pertenece a otro profesional, a otro día o está inactiva
- **THEN** la base la acepta

### Requirement: Exclusión de turnos que ocupan agenda
La disponibilidad MUST excluir todo hueco que se superponga con un turno del mismo profesional en estado distinto de `cancelado` (RN-AG-01). Los turnos cancelados MUST liberar su horario.

#### Scenario: Turno reservado ocupa el hueco
- **WHEN** existe un turno `reservado` de 10:00 a 10:30 y se consulta con duración 30 minutos
- **THEN** el hueco de 10:00 no aparece y los de 09:30 y 10:30 sí

#### Scenario: Turno cancelado libera el hueco
- **WHEN** el único turno de 10:00 a 10:30 está `cancelado`
- **THEN** el hueco de 10:00 aparece disponible

#### Scenario: Superposición parcial con duración larga
- **WHEN** existe un turno de 10:30 a 11:00 y se consulta con un tratamiento de 60 minutos
- **THEN** no aparecen los huecos de 10:00 ni 10:30, pero sí el de 09:30 (09:30–10:30 es contiguo al turno, intervalos semiabiertos `[)`)

### Requirement: Exclusión de bloqueos
La disponibilidad MUST excluir todo hueco que se superponga con un bloqueo activo del profesional (RN-AG-02); un bloqueo dado de baja MUST NOT excluir huecos.

#### Scenario: Bloqueo de medio día
- **WHEN** existe un bloqueo activo de 09:00 a 13:00
- **THEN** el primer hueco del día empieza a las 13:00

#### Scenario: Bloqueo inactivo no afecta
- **WHEN** el bloqueo de 09:00 a 13:00 está dado de baja (inactivo)
- **THEN** el hueco de 09:00 aparece disponible

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
