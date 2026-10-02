# Funcionalidades

Organizadas por **épica** y luego por **historia de usuario**.

## Épica 1: Agenda y disponibilidad

### US-001 — Ver disponibilidad por odontólogo
**Como** paciente
**Quiero** ver horarios libres por odontólogo
**Para** reservar sin preguntar por WhatsApp

**Criterios de aceptación**:
- [ ] CA-1: muestra huecos calculados con duración del tratamiento.
- [ ] CA-2: excluye turnos ocupados y bloqueos.
- [ ] CA-3: funciona en móvil (mobile-first).

**Reglas relacionadas**: RN-AG-01, RN-AG-02, RN-AG-03

### US-002 — Agenda día/semana multi-odontólogo
**Como** secretaria
**Quiero** ver la agenda día/semana por odontólogo
**Para** crear y mover turnos

**Criterios de aceptación**:
- [ ] CA-1: vista día y semana por profesional.
- [ ] CA-2: drag&drop o acción explícita para mover (con validación anti-solape).
- [ ] CA-3: distingue estados y origen online/secretaria.

**Reglas relacionadas**: RN-AG-01, RN-AG-04, RN-GL-01

### US-003 — Mi agenda del día
**Como** odontólogo
**Quiero** ver mi agenda del día
**Para** saber a quién atiendo

**Criterios de aceptación**:
- [ ] CA-1: lista ordenada con paciente, tratamiento y estado.
- [ ] CA-2: solo su agenda (sin datos de otros profesionales).

## Épica 2: Reserva y gestión de turnos

### US-004 — Reservar turno online
**Como** paciente
**Quiero** reservar un turno 24/7
**Para** no llamar ni escribir

**Criterios de aceptación**:
- [ ] CA-1: valida profesional activo y hueco real.
- [ ] CA-2: pide nombre + teléfono válido (sin login obligatorio v1).
- [ ] CA-3: devuelve confirmación + token de gestión.

**Reglas relacionadas**: RN-TU-02, RN-TU-03

### US-005 — Cancelar/reprogramar con anticipación
**Como** paciente
**Quiero** cancelar/reprogramar mi turno
**Para** liberar el horario

**Criterios de aceptación**:
- [ ] CA-1: bloquea si falta menos que la anticipación mínima.
- [ ] CA-2: la reprogramación revalida disponibilidad.
- [ ] CA-3: genera auditoría.

**Reglas relacionadas**: RN-TU-01, RN-TU-03, RN-GL-01

### US-006 — Alta manual y bloqueos
**Como** secretaria
**Quiero** crear turnos manuales y bloquear horarios
**Para** gestionar teléfono/presencial y ausencias

**Criterios de aceptación**:
- [ ] CA-1: alta con paciente nuevo o existente.
- [ ] CA-2: bloqueo con motivo excluye disponibilidad.
- [ ] CA-3: sobreturno solo con marca explícita + auditoría.

**Reglas relacionadas**: RN-AG-02, RN-AG-04

## Épica 3: Recordatorios WhatsApp

### US-007 — Recordatorio 24hs + confirmación 1-clic
**Como** paciente
**Quiero** recibir un recordatorio y confirmar con un clic
**Para** no olvidar mi turno

**Criterios de aceptación**:
- [ ] CA-1: job async agenda el envío 24hs antes.
- [ ] CA-2: el link confirma sin login.
- [ ] CA-3: fallos de envío no rompen la reserva (reintento).

**Reglas relacionadas**: RN-NO-01, RN-NO-02
