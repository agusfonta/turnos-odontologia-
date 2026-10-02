# turnos-odontologia — Instrucciones para Agentes

> Este archivo (y su copia `CLAUDE.md`) es lo PRIMERO que todo agente lee al entrar al repo.
> Generado a partir de `knowledge-base/` y `CHANGES.md`. No editar a mano sin re-sincronizar ambos archivos.

---

## Stack Tecnológico

| Capa | Tecnología | Versión |
|------|------------|---------|
| Backend | Python + FastAPI + SQLAlchemy | Python 3.12, FastAPI 0.110+ |
| Auth | JWT (access + refresh) | — |
| Persistencia | PostgreSQL | 15+ |
| Async/colas | Redis (jobs de recordatorios) | 7+ |
| Frontend | React + TypeScript + Vite | React 18+, TS 5+ |
| Contenedores | Docker / Docker Compose | Compose v2 |
| Integraciones | WhatsApp Business API (solo envío v1) | proveedor a definir |

Detalle completo: [knowledge-base/02_descripcion_general.md](knowledge-base/02_descripcion_general.md)

---

## Base de Conocimiento

La fuente de verdad del dominio vive en `knowledge-base/`. **Leé el archivo relevante ANTES de implementar.**

| Archivo | Cuándo leerlo |
|---------|---------------|
| [01_vision_y_objetivos.md](knowledge-base/01_vision_y_objetivos.md) | Entender propósito y alcance |
| [03_actores_y_roles.md](knowledge-base/03_actores_y_roles.md) | Auth, RBAC, permisos |
| [04_modelo_de_datos.md](knowledge-base/04_modelo_de_datos.md) | Entidades, ERD, migraciones |
| [05_reglas_de_negocio.md](knowledge-base/05_reglas_de_negocio.md) | Reglas codificadas (RN-XX) |
| [06_funcionalidades.md](knowledge-base/06_funcionalidades.md) | Historias de usuario por épica |
| [07_flujos_principales.md](knowledge-base/07_flujos_principales.md) | Flujos E2E |
| [08_arquitectura_propuesta.md](knowledge-base/08_arquitectura_propuesta.md) | Patrones, estructura, env vars |
| [10_preguntas_abiertas.md](knowledge-base/10_preguntas_abiertas.md) | ⚠️ Inconsistencias a resolver ANTES de codear |

> ⚠️ Resolver las preguntas de prioridad **Alta** de `10_preguntas_abiertas.md` antes de arrancar el primer change (login paciente, anticipación mínima, proveedor WhatsApp).

---

## Skills Disponibles

| Agente | Rol | Skills que carga |
|--------|-----|------------------|
| **Backend Core** | FastAPI / Postgres / migraciones | `fastapi`, `supabase-postgres-best-practices`, `test-driven-development` |
| **Backend Aux** | Compose / infra local | `docker-skills` (compose), `test-driven-development` |
| **Frontend** | React / TS / agenda y portal | `vercel-react-best-practices`, `frontend-design`, `web-design-guidelines`, `shadcn`, `webapp-testing` |
| **Orquestación** | OPSX / SDD | skills `openspec-*` del stack global |

Cargá la skill correspondiente al contexto ANTES de escribir código.

> Los compact rules de cada skill los resuelve el orquestador desde `.atl/skill-registry.md` (generado por `skill-registry`; no versionado — no está en el repo). Esta tabla solo mapea skill→rol.

---

## Roadmap de Changes

El plan de implementación completo está en [CHANGES.md](CHANGES.md). Resumen:

- **Total**: 11 changes en 5 fases (Cimientos → Núcleo y acceso → Dominio backend → Notificaciones → Frontend y producción).
- **Camino crítico** (7): `C-01 → C-02 → C-03 → C-04 → C-05 → C-10 → C-11`.
- **Primer change**: `C-01` (foundation-setup).

**Antes de cualquier `/opsx:propose`**: leé [CHANGES.md](CHANGES.md), identificá las dependencias del change y los archivos de "Leer antes".

---

## Reglas Duras

> Reglas globales ya definidas en `~/.claude/CLAUDE.md` (orquestador, governance, TDD, engram): el proyecto las hereda. Acá viven solo las reglas **específicas de este proyecto** + las universales que el global no cubre.

- NUNCA schema Pydantic sin validación estricta → response_model/tipo de retorno siempre, sin campos fantasma.
- NUNCA async con llamadas bloqueantes adentro → `def` por defecto; `async` solo si todo es no-bloqueante.
- NUNCA validar anti-solape solo en la app → constraint de exclusión en Postgres + migración versionada.
- NUNCA `any` en TypeScript → tipado estricto; componentes en PascalCase; `tsconfig` estricto.
- NUNCA commitear ni pushear sin pedido explícito → commits en formato conventional, sin co-autoría IA.
- NUNCA cambiar el modelo sin migración versionada → migración numerada (001, 002…) revisable como diff.
- NUNCA enviar WhatsApp dentro del request → siempre job en Redis con reintento; el turno no depende del envío.
- NUNCA almacenar datos reales de pacientes en el repositorio ni en los ejemplos → solo datos sintéticos/anónimos; seeds y fixtures siempre ficticios.

---

## Flujo de Trabajo

```
1. Leer la KB relevante (knowledge-base/)        → entender el dominio
2. Identificar el change en CHANGES.md           → respetar dependencias
3. /opsx:propose C-NN-nombre                     → proposal + design + specs + tasks
4. Implementar las tasks (cargando skills)       → respetando las reglas duras
5. /opsx:archive C-NN-nombre + marcar [x]        → cerrar el change
```

Aplicar TODAS las reglas duras en cada paso. Ante conflicto entre la KB y este archivo, las reglas duras prevalecen.
