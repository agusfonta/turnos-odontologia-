# Flujos Principales

## Flujo 1: Reserva online

**Disparador**: el paciente abre `/reservar`.
**Actor**: paciente (sin login obligatorio v1).

**Pasos**:
1. Frontend pide profesionales activos y tratamientos.
2. Paciente elige profesional + tratamiento + rango de fechas.
3. Frontend pide `GET /api/disponibilidad`; backend calcula huecos
   (duración tratamiento, turnos existentes, bloqueos).
4. Paciente elige hueco e ingresa nombre + teléfono.
5. Backend valida (RN-TU-02), crea turno `reservado` + token + auditoría.
6. Backend encola job en Redis para recordatorio 24hs antes.
7. Frontend muestra confirmación con opciones de gestión por token.

**Casos de error**:
- Hueco ocupado entre consulta y alta → 409 + huecos actualizados.
- Teléfono inválido → 422 con detalle.
- Profesional inactivo → 404.

## Flujo 2: Gestión de secretaria

**Disparador**: llamada telefónica o atención presencial.
**Actor**: secretaria autenticada.

**Pasos**:
1. Secretaria abre agenda día/semana del profesional.
2. Crea turno manual (paciente nuevo o existente) o mueve uno existente.
3. Backend valida anti-solape (salvo sobreturno explícito) y audita.
4. Si mueve un turno, se reprograman/cancelan sus notificaciones pendientes.

**Casos de error**:
- Solape sin marca de sobreturno → 409.
- Reprogramación fuera de anticipación → 422 (RN-TU-01).

## Flujo 3: Recordatorio y confirmación WhatsApp

**Disparador**: job programado en Redis (24hs antes del turno).
**Actor**: sistema → paciente.

**Pasos**:
1. Worker toma notificaciones `pendientes` con `scheduled_at <= now`.
2. Envía plantilla WhatsApp con links de confirmar/cancelar (token).
3. Marca `enviada` o `fallida` (con reintento).
4. Paciente abre link → backend confirma sin login (RN-NO-02) → audita.

**Casos de error**:
- Fallo de proveedor WA → reintento con backoff, el turno no se altera.
- Token inválido/expirado → 404 sin exponer datos.
