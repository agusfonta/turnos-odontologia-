# turnos-odontologia — Base de Conocimiento

Base de conocimiento generada desde cero (ronda interactiva kb-creator) con
insumo de Discovery (`state.discovery`: 20 competidores, mercado AR/LatAm).

## Índice de Archivos

| Archivo | Contenido |
|---------|-----------|
| [01_vision_y_objetivos.md](01_vision_y_objetivos.md) | Propósito, objetivos por actor, alcance v1.0, fuera de alcance, métricas |
| [02_descripcion_general.md](02_descripcion_general.md) | Stack FastAPI+React, arquitectura single-clínica, integraciones WA, API v1 |
| [03_actores_y_roles.md](03_actores_y_roles.md) | Paciente/odontólogo/secretaria, RBAC, rutas públicas por token |
| [04_modelo_de_datos.md](04_modelo_de_datos.md) | Profesional/paciente/tratamiento/turno/bloqueo/notificación/auditoría + seed |
| [05_reglas_de_negocio.md](05_reglas_de_negocio.md) | RN-AG/TU/NO/GL (anti-solape, anticipación, tokens, auditoría) |
| [06_funcionalidades.md](06_funcionalidades.md) | US-001 a US-007 (agenda, reserva, gestión, recordatorios) |
| [07_flujos_principales.md](07_flujos_principales.md) | Reserva online, gestión secretaria, recordatorio WA |
| [08_arquitectura_propuesta.md](08_arquitectura_propuesta.md) | Patrones, directorios, seguridad JWT, env vars |
| [09_decisiones_y_supuestos.md](09_decisiones_y_supuestos.md) | DD-01 a DD-04, SU-01 a SU-03 |
| [10_preguntas_abiertas.md](10_preguntas_abiertas.md) | IN-01 + 8 preguntas priorizadas |

## Quick Start para Desarrolladores

1. Entender el dominio → [01](01_vision_y_objetivos.md), [03](03_actores_y_roles.md)
2. Entender los datos → [04](04_modelo_de_datos.md)
3. Entender las reglas → [05](05_reglas_de_negocio.md)
4. Entender la arquitectura → [02](02_descripcion_general.md), [08](08_arquitectura_propuesta.md)
5. Implementar → [07](07_flujos_principales.md), [06](06_funcionalidades.md)
6. Antes de codificar → [10](10_preguntas_abiertas.md)

## Resumen Ejecutivo

App web single-clínica (FastAPI + React) para agenda odontológica
multi-odontólogo: reserva 24/7 sin login, anti-solape, bloqueos y recordatorio
WA 24hs. Odontograma, pagos y multi-tenant quedan explícitamente fuera de v1.
