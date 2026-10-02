# Descripción General

## Stack tecnológico

| Capa | Tecnologías | Versión mínima |
|---|---|---|
| Backend | Python + FastAPI + SQLAlchemy | Python 3.12, FastAPI 0.110+ |
| Auth | JWT (access + refresh) | — |
| Persistencia | PostgreSQL | 15+ |
| Async/colas | Redis (jobs de recordatorios) | 7+ |
| Frontend | React + TypeScript + Vite | React 18+, TS 5+ |
| Contenedores | Docker / Docker Compose | Compose v2 |

## Arquitectura general

Monolito modular single-clínica: un deploy por clínica (backend FastAPI +
frontend SPA servido estático + Postgres + Redis). Sin aislamiento
multi-tenant en v1, pero con patrones que permiten evolucionar (capas
domain/application/infrastructure, migraciones versionadas, auditoría).
La prioridad declarada es escalabilidad futura, no velocidad a cualquier costo.

## Integraciones externas

| Servicio | Propósito | Tipo |
|---|---|---|
| WhatsApp Business API (proveedor a definir) | Envío de recordatorios 24hs + confirmación 1-clic | REST/webhook (solo envío en v1) |
| (Futuro) Mercado Pago | Señas y cobros online | Fuera de v1 |
| (Futuro) Google Calendar | Sincronización agenda | Fuera de v1 |

## API REST (v1, dominio agenda)

- `GET /api/profesionales` — odontólogos activos y especialidades.
- `GET /api/disponibilidad?profesional_id&desde&hasta` — huecos libres.
- `POST /api/turnos` — crear reserva (pública con validación, o autenticada).
- `PATCH /api/turnos/{id}` — reprogramar (respeta anticipación mínima).
- `DELETE /api/turnos/{id}` — cancelar (respeta anticipación mínima).
- `GET /api/agenda?profesional_id&dia` — vista día/semana (odontólogo/secretaria).
- `POST /api/bloqueos` — bloquear horarios (secretaria).
- `POST /api/turnos/{id}/confirmar` — confirmación (link 1-clic o secretaria).
