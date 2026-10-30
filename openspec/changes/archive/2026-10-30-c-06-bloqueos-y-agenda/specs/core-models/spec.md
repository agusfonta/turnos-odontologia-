# Spec Delta: core-models

## ADDED Requirements

### Requirement: Vínculo de odontólogo con profesional
La tabla `profesionales` SHALL tener `user_id` nullable con FK a `users` y unicidad, mediante migración versionada. Un profesional sin usuario MUST aceptarse; un usuario MUST vincularse a lo sumo a un profesional. Solo un usuario de rol `odontologo` MUST poder vincularse (validado por la aplicación y el seed, no por la base).

#### Scenario: Profesional sin usuario
- **WHEN** se crea un profesional sin `user_id`
- **THEN** la base lo acepta

#### Scenario: Usuario vinculado a dos profesionales
- **WHEN** se vincula un mismo usuario a un segundo profesional
- **THEN** la base rechaza la fila con violación de unicidad

#### Scenario: Usuario inexistente
- **WHEN** se asigna un `user_id` que no existe en `users`
- **THEN** la base rechaza la fila con violación de FK

#### Scenario: Migración reversible
- **WHEN** se aplica `upgrade` a la 003 y luego `downgrade` a la 002
- **THEN** la columna, su índice único y los triggers de bloqueo desaparecen y los datos de turnos y bloqueos se conservan
