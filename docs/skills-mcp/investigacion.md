# Ficha de Investigación — Skills y MCP
**TP: Integrar una skill propia y un MCP al proyecto odontológico**
**Fecha de elaboración:** 16/10/2026

---

## 1. Necesidad detectada

**Tarea repetible que una skill puede mejorar:**
Cada vez que se va a preparar un change del dominio de turnos, el agente necesita revisar las reglas de negocio (RN-*) para identificar escenarios de borde, ambigüedades y casos de prueba. Esto se repite en cada change y no tiene un procedimiento sistematizado: sin guía, el agente omite casos límite o genera escenarios sin referenciar la regla que los justifica.

**Necesidad de acceso a herramientas que un MCP puede resolver:**
Al preparar C-04, el agente necesita inspeccionar el schema real de la base de datos Postgres local (tablas, columnas, tipos, constraints) para verificar que la migración 002 generó correctamente las tablas `turno`, `bloqueo` y `auditoria_turno`, y que el constraint de exclusión anti-solape existe. Sin acceso directo al schema, el agente trabaja sobre supuestos que podrían no coincidir con el estado real de la DB.

---

## 2. Change elegido

**C-04 `disponibilidad-y-reserva`** (FASE 2 — Dominio de turnos)

- **Estado:** pendiente
- **Dependencia desbloqueada:** C-03 `auth-jwt-rbac` archivado el 2026-10-08 ✓
- **Por qué es el adecuado:** Es el corazón del MVP. Concentra la mayor densidad de reglas de negocio (RN-AG-01/02/03, RN-TU-01/02/03/04, RN-GL-01/02), tiene el mayor riesgo técnico (anti-solape concurrente, exclusión por constraint) y es el más beneficiado por escenarios bien especificados antes de implementar.
- **Cómo contribuyen ambas herramientas:**
  - La skill `domain-scenario-reviewer` produce los escenarios verificables (happy path, error de negocio, borde) que requiere el `spec.md` de C-04.
  - El MCP PostgreSQL permite inspeccionar las tablas ya creadas por las migraciones previas (001) y planificar la migración 002 sobre estructura real, no sobre supuestos.

---

## 3. Skill creadora y diseño de la skill propia

### Skill creadora seleccionada

| Campo | Valor |
|-------|-------|
| **Nombre** | `skill-creator` |
| **Autor / fuente oficial** | AWS Samples — `aws-samples/sample-strands-agents-agentskills` |
| **URL** | https://github.com/aws-samples/sample-strands-agents-agentskills/blob/main/skills/skill-creator/SKILL.md |
| **Fecha de consulta** | 16/10/2026 |
| **Compatibilidad** | Kiro / Claude Code — usa el formato SKILL.md estándar de Anthropic (frontmatter YAML + body Markdown) |
| **Licencia** | MIT (ver LICENSE.txt en el repositorio) |

**Cómo instalarla:**
Copiar el directorio `skills/skill-creator/` del repositorio al path `.agents/skills/skill-creator/` del proyecto y registrarla en `.atl/skill-registry.md`. No requiere instalación externa; es un directorio de archivos Markdown.

**Cómo comprobar que está disponible:**
Verificar que `.agents/skills/skill-creator/SKILL.md` existe y tiene el frontmatter con `name: skill-creator`. En una sesión nueva, el agente encontrará la skill al consultar el registry.

**Cómo usarla para generar una skill propia:**
Activar la skill (cargarla como contexto) y pedirle al agente que cree una nueva skill siguiendo los 6 pasos del proceso:
1. Entender con ejemplos concretos
2. Planificar contenidos reutilizables (scripts, references, assets)
3. Inicializar (crear estructura de directorios)
4. Editar `SKILL.md` y recursos
5. Empaquetar
6. Iterar con uso real

---

### Skill propia a crear: `domain-scenario-reviewer`

| Campo | Valor |
|-------|-------|
| **Nombre** | `domain-scenario-reviewer` |
| **Ubicación** | `.agents/skills/domain-scenario-reviewer/SKILL.md` |
| **Propósito** | Dado un change pendiente y su conjunto de reglas RN-*, generar escenarios verificables (happy path, error de negocio, borde), detectar ambigüedades en las reglas y producir una checklist de casos de prueba con referencia a la RN-* que los justifica |
| **Cuándo se activa** | Antes de escribir `spec.md` o `tasks.md` para cualquier change que involucre reglas de dominio (RN-AG-*, RN-TU-*, RN-NO-*, RN-GL-*) |
| **Entradas necesarias** | Archivo de reglas (`knowledge-base/05_reglas_de_negocio.md`), nombre del change, lista de RN-* relevantes al change |
| **Procedimiento** | 1. Leer las RN-* indicadas. 2. Para cada regla, generar al menos un escenario en formato Given/When/Then. 3. Identificar ambigüedades o precondiciones no cubiertas. 4. Producir la lista ordenada: happy paths primero, errores de negocio, casos de borde. 5. Listar preguntas abiertas detectadas. |
| **Resultado esperado** | Lista de escenarios con formato `ESCENARIO-NN: [tipo] — [descripción]` / `Given / When / Then` + sección "Preguntas abiertas detectadas" |
| **Criterios de revisión** | Al menos 1 happy path, 1 error de negocio y 1 borde por cada RN-* relevante; cada escenario referencia explícitamente su código RN-*; no hay escenarios sin justificación en la KB |
| **Dónde se referencia** | `.atl/skill-registry.md` (trigger: "preparar spec de un change con reglas de dominio") y `AGENTS.md` |

---

## 4. Comparación de servidores MCP y elección

### Candidato A — `@modelcontextprotocol/server-postgres` (oficial Anthropic)

| Dimensión | Detalle |
|-----------|---------|
| **Propósito** | Acceso read-only a PostgreSQL para LLMs |
| **Capacidades** | Una sola herramienta: `query` (SELECT dentro de transacción READ ONLY). Sin inspección de schema, sin escrituras, sin DDL |
| **Compatibilidad** | Claude Desktop, cualquier cliente MCP — pero SDK 1.0.1 no puede negociar protocolo post-2024-11-05 |
| **Instalación** | `npx -y @modelcontextprotocol/server-postgres <connection-string>` |
| **Estado actual** | **Archivado y deprecated desde julio 2025.** Última publicación: 4/12/2024. npm lo marca como deprecated |
| **Credenciales** | Connection string en argumento CLI (sin gestión de secretos) |
| **Costo** | Gratuito, MIT |
| **Limitación crítica** | Deprecado, SDK obsoleto, sin `schema()` ni `list_tables()` — no sirve para inspeccionar estructura |

**Fuente:** https://startdebugging.net/2026/08/migrate-off-archived-mcp-reference-servers/ (consultada 16/10/2026)

---

### Candidato B — `@sarmadparvez/postgresql-mcp`

| Dimensión | Detalle |
|-----------|---------|
| **Propósito** | Acceso read-write (o read-only configurable) a cualquier PostgreSQL |
| **Capacidades** | 5 herramientas: `query` (SELECT), `execute` (writes/DDL), `schema` (columnas/tipos/PKs), `list_tables` (tablas + tamaño), `transaction` (multi-statement atómico) |
| **Compatibilidad** | Claude Desktop, Cursor, Windsurf, Kiro — cualquier cliente MCP estándar |
| **Instalación** | `npm install -g @sarmadparvez/postgresql-mcp` (Node.js 18+) |
| **Estado actual** | Activo. Publicado marzo 2025, MIT, sin dependencias de cloud |
| **Credenciales** | Connection string en argumento CLI; modo read-only vía `?mode=readonly` en la URL |
| **Costo** | Gratuito, sin servicios pagos |
| **Repo oficial** | https://github.com/sarmadparvez/postgresql-mcp (consultado 16/10/2026) |

---

### Elección: Candidato B — `@sarmadparvez/postgresql-mcp`

**Justificación:** El candidato A está deprecado y su SDK ya no es compatible con los clientes actuales. El candidato B está activo, tiene `schema()` y `list_tables()` que son exactamente las herramientas necesarias para inspeccionar las tablas de la migración 002 de C-04, y ofrece modo `?mode=readonly` para eliminar el riesgo de escritura accidental sobre la DB de desarrollo.

---

### Pasos de instalación y configuración

**Requisitos previos:**
- Node.js 18+ instalado
- Stack local levantado (`docker compose up postgres`) con la DB `turnos_odontologia`

**Paso 1 — Instalar globalmente:**
```bash
npm install -g @sarmadparvez/postgresql-mcp
```

**Paso 2 — Obtener la ruta del script instalado:**
```bash
npm root -g
# Ejemplo Linux/macOS: /usr/local/lib/node_modules
# Ejemplo Windows:     C:\Users\<tu-usuario>\AppData\Roaming\npm\node_modules
# El script queda en:  <npm-root>/@sarmadparvez/postgresql-mcp/index.js
```

**Paso 3 — Configurar en Kiro (`.kiro/settings/mcp.json`):**
```json
{
  "mcpServers": {
    "postgres-dev": {
      "command": "node",
      "args": [
        "<npm-root>/@sarmadparvez/postgresql-mcp/index.js",
        "postgresql://<usuario>:<password>@localhost:5432/turnos_odontologia?mode=readonly"
      ],
      "disabled": false
    }
  }
}
```
> ⚠️ No commitear esta configuración con la connection string real. Usar `.kiro/settings/mcp.json` que ya está en `.gitignore`, o reemplazar credenciales por variables de entorno.

**Paso 4 — Comprobar la conexión:**
Pedir al agente: `"Usa el MCP postgres-dev para listar las tablas disponibles."` → debe invocar `list_tables` y devolver la lista.

**Paso 5 — Ejecutar una herramienta real:**
```
schema({ schema: "public", table: "turno" })
```
Debe devolver columnas, tipos, nullability, PKs y constraints de la tabla `turno`.

**Límites para datos de prueba:**
- Solo se usa contra la DB local de Docker, nunca contra producción.
- Modo `?mode=readonly` desactiva `execute` y `transaction`: el agente solo puede leer.
- La connection string con credenciales reales nunca se commitea al repo.

---

## 5. Archivos de la fundación que se prevé actualizar

| Archivo | Motivo |
|---------|--------|
| `.agents/skills/domain-scenario-reviewer/SKILL.md` | Skill nueva a crear con la skill-creator |
| `.agents/skills/skill-creator/SKILL.md` | Skill creadora a instalar (copiar desde aws-samples) |
| `.atl/skill-registry.md` | Registrar `domain-scenario-reviewer` con su trigger |
| `AGENTS.md` | Agregar fila en tabla de Skills Disponibles y cuándo usar la nueva skill |
| `.kiro/settings/mcp.json` | Configuración del servidor MCP (local, fuera del repo versionado) |
| `README.md` | Sección de integraciones MCP con pasos reproducibles |

---

## 6. Fuentes

| Recurso | URL | Fecha de consulta |
|---------|-----|-------------------|
| skill-creator (AWS Samples) — SKILL.md oficial | https://github.com/aws-samples/sample-strands-agents-agentskills/blob/main/skills/skill-creator/SKILL.md | 16/10/2026 |
| skill-creator (kiro-powers) — README | https://github.com/hebertzhu/kiro-powers/blob/main/skill-creator/README.md | 16/10/2026 |
| @sarmadparvez/postgresql-mcp — README | https://github.com/sarmadparvez/postgresql-mcp | 16/10/2026 |
| Migración off deprecated MCP servers (Anthropic official) | https://startdebugging.net/2026/08/migrate-off-archived-mcp-reference-servers/ | 16/10/2026 |
| microsoft/postgres-mcp — README | https://github.com/microsoft/postgres-mcp | 16/10/2026 |
| Documentación oficial de skills (Claude Platform) | https://platform.claude.com/docs/es/managed-agents/skills | 16/10/2026 |
