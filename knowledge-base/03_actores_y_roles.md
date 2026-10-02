# Actores y Roles

## Actores del sistema

| Actor | Descripción | Cómo interactúa |
|---|---|---|
| Paciente | Persona que reserva atención | Portal público responsive (sin login obligatorio en v1, a confirmar) |
| Odontólogo | Profesional que atiende | SPA autenticada: su agenda día/semana |
| Secretaria | Gestiona la agenda de la clínica | SPA autenticada: agenda multi-odontólogo, ABM turnos/bloqueos |

## RBAC — Matriz de permisos

| Rol | Turnos | Agenda | Bloqueos | Profesionales/Tratamientos | Reportes |
|---|---|---|---|---|---|
| paciente | crear propio, cancelar/reprog propio | ver disponibilidad pública | — | ver | — |
| odontologo | ver propios, confirmar | ver propia | ver | ver | ver propios |
| secretaria | CRUD todos | ver todas | CRUD | CRUD | ver todos |

## Rutas públicas

- `/reservar` — consulta de disponibilidad y alta de turno (sin auth obligatoria en v1).
- `/turnos/{token}/confirmar` — confirmación 1-clic desde WhatsApp.
- `/turnos/{token}/cancelar` — cancelación con token (respeta anticipación).
