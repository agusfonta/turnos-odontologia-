# Visión y Objetivos

## Propósito del sistema

Sistema web single-clínica para gestión de turnos y agenda odontológica que
reemplaza la coordinación manual por WhatsApp/papel, eliminando dobles
reservas y el costo de confirmación manual.

## Objetivos por actor

| Actor | Objetivo principal | Objetivos secundarios |
|---|---|---|
| Paciente | Reservar sin llamar ni escribir | Cancelar/reprogramar con anticipación |
| Odontólogo | Ver su agenda del día/semana | Recibir agenda actualizada sin huecos falsos |
| Secretaria | Gestionar agenda completa (crear/mover/bloquear) | Confirmar asistencia y reducir no-show |

## Alcance v1.0

- Agenda por odontólogo con vista día/semana.
- Reserva online 24/7 (link compartible).
- Cancelación y reprogramación con anticipación configurable.
- Alta manual y bloqueo de horarios por secretaria.
- Recordatorio automático por WhatsApp 24hs antes + confirmación.
- Prevención de solapamientos y sobreturnos explícitos.
- Duración por tratamiento configurable.

## Fuera de alcance

- Odontograma, periodontograma e historia clínica completa.
- Pagos online, señas por Mercado Pago y facturación AFIP/ARCA.
- Liquidaciones de obras sociales/prepagas.
- Chatbot conversacional de WhatsApp (v1 solo envío).
- Multi-sucursal y multi-tenant (un deploy por clínica).

## Métricas de éxito

- Cero dobles reservas por odontólogo.
- Reducción de ausentismo vs. línea base manual.
- Tiempo de gestión de secretaria por turno reducido.
- % de reservas online sobre total de turnos.
