# Tasks: c-07-autogestion-por-token

> Governance **MEDIO**: implementar con checkpoints (al cerrar las secciones 3, 5 y 6, resumen al orquestador con decisiones no obvias). Fuera de alcance: cambiar firma/flujo de `reservar_turno`, de la UoW o de `reprogramar_turno`/`cancelar_turno` (C-05); solo se **agrega** `confirmar_turno` y la capa de token.
> **Sin migración de DB**: alembic queda en `003`; no se crea nada en `alembic/versions/`.
> **Antes del apply**: confirmar con el usuario las Open Questions 1–9 de `design.md` (los defaults están aplicados en specs y en estas tasks).
> Strict TDD: RED → GREEN → TRIANGULATE → REFACTOR en cada task; ningún código de producción sin un test rojo previo que falle por la razón esperada; suite completa verde al cerrar cada task. Tests de caracterización que pasan de entrada se validan por **mutación temporal** y se anota en el resumen.
> Skills: `fastapi`, `test-driven-development`, `uow-transacciones`, `turno-use-case`. Todo `def`. Schemas Pydantic `extra="forbid"` con `response_model`. Datos de tests solo sintéticos (helpers de `tests/support_gestion.py`).
> Diseño de referencia: `design.md` D1–D8. Requisitos: `specs/turnos/spec.md`.

## 1. Safety net

- [x] 1.1 Baseline: `pytest` completo en `src/backend` contra PG real; registrar "N tests passing" (skips explicitados). Si algo falla, FRENAR y reportar como falla preexistente. Verificar: 0 failed / 0 error; `alembic heads` = `003`.

## 2. Repositorio

- [x] 2.1 `TurnoRepository.id_por_token` (D1). RED: `tests/test_repos_agenda.py::test_id_por_token_devuelve_el_turno` (falla: método inexistente). GREEN: `SELECT id … WHERE token_publico = :t`. TRIANGULATE: token inexistente → `None`; con dos turnos devuelve el correcto; un turno con `token_publico` nulo no matchea con ningún string. REFACTOR en verde.
- [x] 2.2 Lectura del detalle público (D4). RED: `test_detalle_publico_incluye_nombres_de_profesional_y_tratamiento` sobre una lectura de `TurnoRepository` (turno + `Profesional.nombre` + `Tratamiento.nombre`). GREEN con LEFT JOIN. TRIANGULATE: turno sin tratamiento → `tratamiento_id`/`tratamiento_nombre` nulos; turno `cancelado` se devuelve igual. REFACTOR en verde.

## 3. Caso de uso `confirmar_turno` (`app/application/gestion_turnos.py`)

- [x] 3.1 Confirmación (D2, D8). RED: `tests/test_gestion_turnos.py::test_confirmar_reservado_pasa_a_confirmado_y_audita` con actor paciente (falla: función inexistente). GREEN: receta D2 en un `with` con `obtener_para_actualizar`, `transicionar`, auditoría `confirmar` `{estado_anterior}`, `flush()`, DTO `TurnoGestionado`. TRIANGULATE: `confirmado` → no-op, mismo DTO, 0 auditorías nuevas (leído desde otra sesión); `cancelado`/`atendido`/`ausente` → `TransicionNoPermitidaError` sin auditoría; `inicio <= ahora` en `reservado` → `AnticipacionInsuficienteError` (`min_horas=0`) sin cambios; dentro de la ventana de `CANCEL_MIN_HOURS` → acepta; inexistente → `TurnoNoEncontradoError`; actor secretaria → auditoría con `actor_user_id`; `token_publico` sin cambios. REFACTOR en verde.
- [x] 3.2 Guardas de arquitectura: `pytest tests/test_transacciones_arquitectura.py` verde (sin `commit`/`rollback` en `application/`); `confirmar_turno` es `def`.
- [x] 3.3 Checkpoint MEDIO: resumen al orquestador (orden de chequeos de D2, idempotencia). Suite completa verde.

## 4. Schemas (`app/domain/schemas.py`)

- [x] 4.1 Schemas públicos (D4). RED: `tests/test_schemas_autogestion.py`: `TurnoReprogramarPublico` acepta solo `inicio` aware y rechaza `sobreturno`, campos extra e `inicio` naive; el conjunto de campos de `TurnoPorTokenOut` es **exactamente** `{inicio, fin, estado, profesional_id, tratamiento_id, gestionable_hasta}` y el de `TurnoPorTokenDetalle` agrega solo `{profesional_nombre, tratamiento_nombre}` (guarda anti-fuga). GREEN. TRIANGULATE: ambos aceptan los 5 estados y `tratamiento_*` nulos; rechazan `paciente_id`/`id`/`token_publico` como extra. REFACTOR en verde.

## 5. Capa de token (`app/application/autogestion.py`)

- [x] 5.1 `resolver_token` (D1, D6). RED: `tests/test_autogestion.py::test_resolver_token_valido_devuelve_id`. GREEN: regex `^[A-Za-z0-9_-]{1,64}$` + `id_por_token` en UoW de lectura. TRIANGULATE: inexistente → `TurnoNoEncontradoError`; con `/`, espacio, `%`, `.` o 65 caracteres → `TurnoNoEncontradoError` **sin abrir UoW** (verificar con `factoria_espia`: bitácora vacía); string vacío → 404. REFACTOR en verde.
- [x] 5.2 `consultar_por_token` (D4). RED: `test_consultar_por_token_devuelve_detalle_publico` (DTO frozen con nombres y `gestionable_hasta = inicio - CANCEL_MIN_HOURS` vía `get_settings()`, sin hardcode). TRIANGULATE: `CANCEL_MIN_HOURS=3` cambia `gestionable_hasta`; token inválido → 404; no crea auditoría. REFACTOR en verde.
- [x] 5.3 Operaciones por token sobre los casos de uso de C-05 (D1). RED: `test_cancelar_por_token_usa_actor_paciente` (auditoría `cancelar` con `actor_tipo=paciente`, `actor_user_id` nulo). GREEN: `cancelar_por_token`, `reprogramar_por_token` (construye `TurnoReprogramar(inicio, sobreturno=False)`), `confirmar_por_token` = `resolver_token` + caso de uso con `Actor(PACIENTE, None)`. TRIANGULATE: cancelar dentro de la ventana → `AnticipacionInsuficienteError`; borde exacto `CANCEL_MIN_HOURS` → acepta; reprogramar a hueco libre → `reservado` y horario nuevo; reprogramar a hueco ocupado → `HuecoOcupadoError` con huecos del nuevo día; reprogramar fuera de plazo → 422 sin cambios; token inválido en cada operación → 404 sin tocar la base. Caracterización: ninguna operación cambia `token_publico` (validar por mutación). REFACTOR en verde.
- [x] 5.4 Checkpoint MEDIO: resumen al orquestador. `pytest tests/test_autogestion.py tests/test_gestion_turnos.py tests/test_transacciones_arquitectura.py` verde.

## 6. API

- [x] 6.1 `GET /api/turnos/por-token/{token}` (D3). RED: `tests/test_api_autogestion.py::test_get_por_token_200_sin_datos_del_paciente` (falla: 404 de ruta). GREEN: `app/api/autogestion.py` (`APIRouter(prefix="/turnos/por-token")`, `def`, `response_model=TurnoPorTokenDetalle`, `token: Annotated[str, Path()]` sin restricciones) registrado en `app/main.py` antes de `turnos_router`. TRIANGULATE: el JSON no contiene nombre/teléfono del paciente, `paciente_id`, `id`, `token_publico`, `origen` ni `sobreturno`; `inicio`/`fin`/`gestionable_hasta` con offset de la clínica; turno cancelado → 200 `estado=cancelado`; no requiere `Authorization`. REFACTOR en verde.
- [x] 6.2 404 uniforme (spec "Token inválido sin fuga de datos"). RED: test parametrizado sobre las 4 rutas con token inexistente, malformado (`%2F`, 65 caracteres, caracteres no URL-safe) → 404 `turno_no_encontrado` con cuerpo idéntico entre causas y entre rutas (no 422); base, auditoría y cola sin cambios; `caplog` no contiene el token en ningún registro. GREEN si hace falta ajustar. Validar por mutación (agregar `pattern` al `Path` → 422 → rojo) y revertir.
- [x] 6.3 `POST /api/turnos/por-token/{token}/confirmar`. RED: `test_confirmar_por_token_200`. GREEN: ruta 200 `TurnoPorTokenOut`, sin efecto en la cola. TRIANGULATE: reconfirmar → 200 sin auditoría nueva; cancelado → 422 `transicion_no_permitida`; turno ya iniciado (insertado directo con `inicio` pasado) → 422 `anticipacion_insuficiente`; dentro de la ventana → 200; la cola conserva el job con el mismo score. REFACTOR en verde.
- [x] 6.4 `DELETE /api/turnos/por-token/{token}`. RED: `test_cancelar_por_token_200_y_desencola`. GREEN: ruta 200 `TurnoPorTokenOut`, `cola.cancelar(dto.id)` post-retorno. TRIANGULATE: fuera de plazo → 422 `anticipacion_insuficiente` con `min_horas` y la cola intacta; terminal → 422; el horario vuelve a `GET /api/disponibilidad`; `CANCEL_MIN_HOURS=3` (override de settings) y turno a 4 h → 200; Redis caído → 200 + warning con `turno_id` (sin token). REFACTOR en verde.
- [x] 6.5 `PATCH /api/turnos/por-token/{token}`. RED: `test_reprogramar_por_token_200_y_reencola`. GREEN: ruta 200 `TurnoPorTokenOut`, body `TurnoReprogramarPublico`, `cola.encolar(dto.id, dto.inicio)` post-retorno. TRIANGULATE: `sobreturno` en el body → 422; `confirmado` → `estado=reservado`; 409 `hueco_ocupado` con `huecos` (turno intacto); fuera de plazo → 422; inicio naive/fuera de grilla/pasado → 422; auditoría `reprogramar` con actor `paciente` leída desde otra sesión; la consulta por el mismo token devuelve el horario nuevo. REFACTOR en verde.
- [x] 6.6 `POST /api/turnos/{turno_id}/confirmar` (secretaria, `app/api/turnos.py`). RED: `tests/test_api_gestion_turnos.py::test_secretaria_confirma_200`. GREEN: ruta `require_secretaria`, 200 `TurnoGestionadoOut`, `Actor(SECRETARIA, user.id)`. TRIANGULATE: sin token / token inválido → 401; `odontologo` → 403 sin cambios; inexistente → 404; UUID inválido → 422; auditoría con `actor_user_id` de la secretaria. REFACTOR en verde.
- [x] 6.7 Orden commit → efecto por token: con `factoria_espia` y una cola fake que verifica desde **otra** conexión que el cambio ya es visible, bitácora `[..., "commit", "encolar"|"cancelar"]` para PATCH y DELETE por token; 404/409/422 → cola sin tocar. Validar por mutación (efecto antes del caso de uso → rojo) y revertir.
- [x] 6.8 Checkpoint MEDIO: resumen al orquestador. Suite completa verde.

## 7. Concurrencia (`tests/test_autogestion_concurrencia.py`, `threading.Barrier`)

- [x] 7.1 Confirmar ↔ cancelar (spec "Confirmación concurrente con cancelación"): mismo turno `reservado` futuro, confirmación y cancelación por token simultáneas → 0×500, estado final `cancelado`, auditorías nuevas = operaciones exitosas. Correr 3 veces sin flakiness.
- [x] 7.2 Reprogramación por token vs alta manual y vs reserva pública al mismo hueco → exactamente un éxito, un 409 `hueco_ocupado`, 0×500, sin superposiciones (consulta de pares solapados no cancelados sin sobreturno = 0). Correr 3 veces sin flakiness.

## 8. Cierre

- [x] 8.1 Docstrings: `app/application/autogestion.py` (resolución en lectura previa y por qué es segura, actor paciente, 404 uniforme), `app/api/autogestion.py` y la cabecera de `app/api/turnos.py` (ruta de confirmación). Verificar: `pytest tests/test_transacciones_arquitectura.py` verde.
- [x] 8.2 Integración final: `pytest` completo verde con N(baseline) + nuevos; ruff/mypy si están configurados sin errores nuevos; `alembic heads` = `003` y `git status` sin archivos nuevos en `alembic/versions/`; `rg -n "\.commit\(\)|\.rollback\(\)" src/backend/app/application src/backend/app/api` vacío; `rg -n "async def" src/backend/app/api/autogestion.py src/backend/app/application/autogestion.py` vacío. Registrar la tabla TDD Cycle Evidence. No commitear ni pushear sin pedido explícito.

## Workflow follow-up

- [x] Open Questions 1–9 de `design.md` confirmadas por el usuario (defaults aprobados; marcadas [DECIDIDO]).
- [x] Registradas DD-13 (token estable/sin TTL) y DD-14 (reconfirmación idempotente) en `knowledge-base/09_decisiones_y_supuestos.md`.
- Anotar para C-08: el worker debe decidir si omite el recordatorio de turnos ya `confirmado`.
- `openspec-verify`, luego `/opsx:archive c-07-autogestion-por-token` y marcar C-07 `[x]` en `CHANGES.md`.
