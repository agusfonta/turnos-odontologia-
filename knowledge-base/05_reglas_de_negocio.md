# Reglas de Negocio

Cada regla tiene un código único `RN-{DOMINIO}-{NN}` para trazabilidad.

## Dominio: Agenda (RN-AG)

- **RN-AG-01**: Un odontólogo no puede tener dos turnos superpuestos, salvo
  sobreturno marcado explícitamente por secretaria — evita dobles reservas.
- **RN-AG-02**: Los bloqueos (vacaciones, feriados, motivos) eliminan
  disponibilidad del rango — la agenda nunca ofrece huecos falsos por bloqueo.
- **RN-AG-03**: La duración del turno sale del tratamiento asociado (o del slot
  por defecto del profesional) — sin duraciones, no hay cálculo de huecos.
- **RN-AG-04**: Los sobreturnos requieren rol secretaria y quedan auditados.

## Dominio: Turnos (RN-TU)

- **RN-TU-01**: No se puede cancelar/reprogramar con menos de la anticipación
  mínima configurable (default 24h) — protege la agenda (caso real AR usa 3h,
  por eso es configurable).
- **RN-TU-02**: La reserva online valida profesional activo, horario dentro de
  disponibilidad y datos mínimos del paciente (nombre + teléfono válido).
- **RN-TU-03**: Cada turno público lleva token único para confirmar/cancelar
  sin login — sin token válido, no hay operación pública.
- **RN-TU-04**: Los estados siguen el ciclo
  reservado → confirmado → atendido/ausente, o → cancelado — sin saltos.

## Dominio: Notificaciones (RN-NO)

- **RN-NO-01**: Todo turno confirmado agenda un recordatorio WhatsApp 24hs
  antes vía job en Redis — el envío es async, nunca bloquea la reserva.
- **RN-NO-02**: La confirmación 1-clic desde WhatsApp confirma sin login.

## Dominio: Excepciones globales

- **RN-GL-01**: Toda creación/movimiento/cancelación de turno genera un
  registro de auditoría append-only (actor, acción, timestamp).
- **RN-GL-02**: Los horarios se persisten en timestamptz (zona de la clínica
  America/Argentina/Buenos_Aires) — sin zona explícita, no se agenda.
