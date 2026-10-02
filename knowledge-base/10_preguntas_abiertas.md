# Preguntas Abiertas

## Inconsistencias detectadas

### IN-01 — Single-clínica vs prioridad escalabilidad
**Documento A dice**: 01/08 definen single-clínica (un deploy por clínica).
**Documento B dice**: P5 prioriza escalabilidad.
**Impacto**: si "escalabilidad" significaba multi-tenant día 1, el modelo de
datos y el aislamiento están sub-especificados.
**Resolución propuesta**: mantener single-clínica v1 con capas preparadas
(DD-01); tratar multi-tenant como change futuro.

## Preguntas abiertas (priorizadas)

| Prioridad | Pregunta | Bloquea | Decisor |
|---|---|---|---|
| Alta | ¿Login paciente o nombre+teléfono por turno? | US-004/005 | Product Owner |
| Alta | ¿Anticipación mínima definitiva: 24h o 2–3h? | RN-TU-01, seed | Clínica |
| Alta | ¿Proveedor WhatsApp (Business API directo vs BSP) y quién paga por mensaje? | RN-NO-01, infra | Tech Lead |
| Media | ¿Duraciones fijas por tratamiento desde v1 o slot único? | US-001, seed | Clínica |
| Media | ¿Sillones/boxes compartidos entre profesionales? | Modelo de datos | Clínica |
| Media | ¿Deduplicación de pacientes por teléfono/DNI? | US-004/006 | Equipo técnico |
| Baja | ¿Lista de espera automática entra en v1 o post? | Roadmap | Product Owner |
| Baja | ¿Plazo de lanzamiento y clínica piloto? | Planificación | Product Owner |
