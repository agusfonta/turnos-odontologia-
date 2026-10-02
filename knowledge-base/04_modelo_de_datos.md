# Modelo de Datos

## Dominios

- **Agenda**: profesionales, tratamientos (duraciones), turnos, bloqueos.
- **Personas**: pacientes (datos mínimos de contacto).
- **Notificaciones**: recordatorios y confirmaciones por WhatsApp.
- **Auditoría**: quién creó/movió/canceló cada turno.

## ERD (textual)

```
Profesional (1) ──< Turno >── (1) Paciente
Profesional (1) ──< Bloqueo
Tratamiento (1) ──< Turno (duración por defecto del tratamiento)
Turno (1) ──< Notificacion
Turno (1) ──< AuditoriaTurno
```

## Entidades

### Profesional
- Atributos: id (uuid), nombre, matrícula, especialidad, activo (bool), slot_default_min (int).
- Relaciones: 1—N Turno, 1—N Bloqueo.
- Constraints: matrícula única; solo turnos si activo.
- Índices: (activo), (especialidad).

### Paciente
- Atributos: id (uuid), nombre, teléfono (E.164), dni (nullable), created_at.
- Relaciones: 1—N Turno.
- Constraints: teléfono con formato válido; unicidad (teléfono+dni) a definir.
- Índices: (teléfono).

### Tratamiento
- Atributos: id, nombre, duracion_min (int), activo.
- Relaciones: 1—N Turno.
- Constraints: duracion_min > 0.

### Turno
- Atributos: id (uuid), profesional_id, paciente_id, tratamiento_id (nullable),
  inicio (timestamptz), fin (timestamptz), estado (reservado/confirmado/
  cancelado/ausente/atendido), origen (online/secretaria),
  token_publico (nullable, único), created_by, timestamps.
- Relaciones: N—1 Profesional/Paciente/Tratamiento.
- Constraints: fin > inicio; sin solape por profesional salvo sobreturno
  explícito; cancelación/reprogramación respeta anticipación mínima.
- Índices: (profesional_id, inicio), (estado), (paciente_id).

### Bloqueo
- Atributos: id, profesional_id, desde, hasta, motivo.
- Constraints: bloquea disponibilidad (no genera turnos en el rango).

### Notificacion
- Atributos: id, turno_id, canal (whatsapp), tipo (recordatorio/confirmación),
  estado (pendiente/enviada/fallida), scheduled_at, sent_at.

### AuditoriaTurno
- Atributos: id, turno_id, actor, acción, detalle (JSON), created_at (append-only).

## Seed data inicial

- Roles (paciente, odontologo, secretaria) y un usuario secretaria inicial.
- 1 profesional de ejemplo + 3 tratamientos base (limpieza 30m, consulta 20m,
  conducto 60m) + anticipación mínima (24h) como parámetro configurable.
