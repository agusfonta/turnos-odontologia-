# Design: c-07-autogestion-por-token

> Governance **MEDIO** (lógica de negocio). Motivación: `proposal.md` — Why. Requisitos: `specs/turnos/spec.md`. Patrón base: C-04b (UoW + DTO + efectos post-commit) y C-05 (D1–D11: `Actor`, orden de locks, anticipación por actor, errores). Skills: `uow-transacciones`, `turno-use-case`, `fastapi`, `test-driven-development`.

## Context

Estado verificado en `main` (`06d0b3f`):

- `turnos.token_publico varchar(64) NULL UNIQUE` (002) ⇒ ya hay índice único para buscar por token. Se genera con `secrets.token_urlsafe(32)` (43 caracteres, alfabeto `[A-Za-z0-9_-]`) en `reservas.reservar_turno` y en `gestion_turnos.alta_manual_turno`, y se guarda **en claro**. Turnos del seed pueden tenerlo nulo (nunca matchean).
- `app/application/gestion_turnos.py` (C-05): `Actor(tipo, user_id)`, `cancelar_turno(uow_factory, turno_id, *, actor, ahora)` y `reprogramar_turno(uow_factory, turno_id, datos: TurnoReprogramar, *, actor, ahora, tz)`, ambos con `TurnoGestionado` DTO. La rama `AuditoriaActor.PACIENTE` de `verificar_anticipacion` ya existe y está testeada a nivel de aplicación; `reprogramar_turno` rechaza `sobreturno=True` con actor ≠ secretaria (`ValueError`). **No existe `confirmar_turno`.**
- `TurnoRepository`: `profesional_de`, `bloquear_agenda`, `obtener_para_actualizar` (FOR UPDATE + `populate_existing`). No hay búsqueda por token.
- `RecordatorioQueue.cancelar` (ZREM) **ya existe** (C-05 D10): no hay que agregarlo.
- `TurnoNoEncontradoError` (404 `turno_no_encontrado`), `TransicionNoPermitidaError` (422), `AnticipacionInsuficienteError` (422, `min_horas`) ya existen.
- `auditoria_turno.accion` es `String(32)` sin CHECK ⇒ `confirmar` no requiere migración. Alembic está en `003`.
- `app/api/turnos.py` concentra reserva + gestión de secretaria; todas las rutas son `def`.

## Goals / Non-Goals

**Goals:**
- Puerta pública por token sobre los **mismos** casos de uso de C-05 (sin duplicar reglas), con actor `paciente`.
- 404 uniforme e indistinguible para cualquier token inválido.
- `confirmar_turno` único para ambas puertas (token y secretaria).

**Non-Goals:**
- Rotación, vencimiento o hash del token en reposo; rate limiting de rutas públicas (ver Open Questions — defaults: no en v1).
- Página/SPA de autogestión (C-09) y links en la plantilla de WhatsApp (C-08).
- Que el paciente cambie profesional/tratamiento o reserve otro turno desde el token.
- Que la confirmación afecte la cola (C-08 decide si el worker omite turnos confirmados o cancelados).

## Decisions

### D1. Resolución del token en una lectura previa, luego el caso de uso por id

- `app/application/autogestion.py::resolver_token(uow_factory, token) -> uuid.UUID`: valida formato con `TOKEN_RE = ^[A-Za-z0-9_-]{1,64}$` (si no matchea → `TurnoNoEncontradoError` **sin** abrir UoW), y si no, `TurnoRepository.id_por_token(token)` en una UoW de lectura; `None` → `TurnoNoEncontradoError`.
- Luego cada operación llama al caso de uso existente con `Actor(AuditoriaActor.PACIENTE, None)`: `cancelar_turno(...)`, `reprogramar_turno(..., TurnoReprogramar(inicio=..., sobreturno=False))`, `confirmar_turno(...)`.
- **Por qué es seguro con dos transacciones**: el token es inmutable (D5) y los turnos nunca se borran físicamente (baja lógica), así que `token → id` no puede cambiar entre la lectura y la escritura; el estado vigente lo relee el caso de uso con `FOR UPDATE`.
- Alternativa descartada: agregar `token` como parámetro alternativo a `cancelar_turno`/`reprogramar_turno` — cambia la firma de casos de uso ya archivados y mezcla autenticación (resolver el token) con reglas de negocio. Alternativa descartada: resolver dentro del mismo `with` duplicando el cuerpo del caso de uso.
- `TurnoRepository.id_por_token(token) -> uuid.UUID | None`: `SELECT id FROM turnos WHERE token_publico = :t` (usa el índice único).

### D2. `confirmar_turno` en `gestion_turnos.py`, compartido por las dos puertas

- Firma: `confirmar_turno(uow_factory, turno_id, *, actor: Actor, ahora) -> TurnoGestionado`.
- Receta en un `with`, en este orden: (1) `obtener_para_actualizar` (`None` → 404); (2) si `estado == CONFIRMADO` → devolver DTO **sin** auditoría (no-op idempotente); (3) `transicionar(estado, CONFIRMADO)` (terminal → `TransicionNoPermitidaError` 422); (4) `inicio <= ahora` → `AnticipacionInsuficienteError(0)` 422; (5) `AuditoriaTurno(accion="confirmar", detalle={"estado_anterior": ...})` → `flush()` → DTO.
- Por qué ese orden: reconfirmar un confirmado ya pasado es inocuo (200); un turno cancelado pasado responde `transicion_no_permitida`, que es más informativo que la anticipación.
- "Ya iniciado" reutiliza `AnticipacionInsuficienteError` con `min_horas=0` (coherente con la regla de secretaria de C-05: "turno ya iniciado → mismo 422"). Sin `CANCEL_MIN_HOURS`: la confirmación no protege la agenda, y el recordatorio llega justamente dentro de las 24 h.
- No toma advisory lock: no ocupa agenda. El `FOR UPDATE` serializa confirmar vs cancelar/reprogramar del mismo turno (spec "Confirmación concurrente con cancelación").

### D3. Router propio `app/api/autogestion.py` (`prefix="/turnos/por-token"`)

| Método y ruta | Auth | Body | 2xx | Errores |
|---|---|---|---|---|
| `GET /api/turnos/por-token/{token}` | pública | — | 200 `TurnoPorTokenDetalle` | 404 |
| `POST /api/turnos/por-token/{token}/confirmar` | pública | — | 200 `TurnoPorTokenOut` | 404/422 |
| `PATCH /api/turnos/por-token/{token}` | pública | `TurnoReprogramarPublico` | 200 `TurnoPorTokenOut` | 404/409/422 |
| `DELETE /api/turnos/por-token/{token}` | pública | — | 200 `TurnoPorTokenOut` | 404/422 |
| `POST /api/turnos/{turno_id}/confirmar` (en `turnos.py`) | `require_secretaria` | — | 200 `TurnoGestionadoOut` | 401/403/404/422 |

- `token: Annotated[str, Path()]` **sin** `min_length`/`pattern`: una restricción de FastAPI devolvería 422 y distinguiría tokens malformados; la validación de formato vive en `resolver_token` (→ 404 uniforme).
- Rutas: `/turnos/por-token/{token}` (2+ segmentos tras `/turnos`) no colisiona con `/turnos/{turno_id}` (1 segmento). `POST /turnos/por-token/confirmar` caería en `/{turno_id}/confirmar` con `turno_id="por-token"` → 422 de UUID; aceptable (no es un token). El router de autogestión se registra **antes** que el de turnos en `main.py` para dejar explícita la precedencia.
- Todo `def`; `response_model` siempre; efectos post-commit en el router: `PATCH` → `cola.encolar(dto.id, dto.inicio)`; `DELETE` → `cola.cancelar(dto.id)`; `confirmar`/`GET` → nada.
- Router de orquestación fino: `token → resolver_token → caso de uso (actor paciente) → efecto → mapear DTO`. Si crecen los efectos, extraer orquestador (C-05 D10).

### D4. Schemas (`app/domain/schemas.py`)

- `TurnoReprogramarPublico`: `inicio: AwareDatetime`, `extra="forbid"` ⇒ `sobreturno` → 422. El router lo convierte en `TurnoReprogramar(inicio=..., sobreturno=False)`.
- `TurnoPorTokenOut` (`extra="forbid"`): `inicio`, `fin` (offset de la clínica), `estado: EstadoTurnoLiteral`, `profesional_id`, `tratamiento_id: int | None`, `gestionable_hasta: AwareDatetime` (= `inicio - CANCEL_MIN_HOURS`, en zona de la clínica). Se arma desde `TurnoGestionado` + settings, sin otra lectura.
- `TurnoPorTokenDetalle(TurnoPorTokenOut)`: + `profesional_nombre: str`, `tratamiento_nombre: str | None`. Solo el `GET` (necesita un join).
- Ninguno incluye `id`, `paciente_*`, `token_publico`, `origen`, `sobreturno`. Test de esquema: el conjunto de campos es exactamente el listado (evita fugas por agregado futuro).
- `consultar_por_token(uow_factory, token) -> TurnoPublicoDTO` (frozen) en `autogestion.py`: resuelve y lee turno + `Profesional.nombre` + `Tratamiento.nombre` (LEFT JOIN) en la misma UoW de lectura (aquí sí un solo `with`, porque es solo lectura).

### D5. Token estable, sin vencimiento propio, en claro (defaults v1)

- No rota al reprogramar/confirmar: los links del recordatorio y la pantalla de confirmación de C-09 siguen funcionando; reprogramar re-encola el recordatorio con el mismo `turno_id`, y el worker (C-08) arma el link desde el token vigente.
- Sin TTL: el límite real son el estado (terminales no operan) y la anticipación. El `GET` sigue respondiendo para turnos pasados/cancelados (el paciente ve qué pasó).
- En claro: hashear (SHA-256 + columna nueva) exige migración 004 y backfill, y protege solo ante una fuga de la DB, que ya expondría todo lo demás. Se deja como Open Question.

### D6. No-fuga y logs

- Un único punto lanza el 404 (`resolver_token`), con el mensaje por defecto de `TurnoNoEncontradoError` ⇒ cuerpo idéntico para inexistente y malformado. Test que compara cuerpos byte a byte entre ambas causas y entre las 4 rutas.
- La aplicación no loguea el token: `logger.warning` de la cola usa `turno_id`; ningún log nuevo incluye el path param. Test con `caplog` que recorre las 4 rutas y verifica que el token no aparece. (El access log de uvicorn queda fuera de la app — ver Risks.)

### D7. Concurrencia

- Reprogramar por token usa `reprogramar_turno` tal cual ⇒ hereda el advisory lock por profesional, `FOR UPDATE`, 23P01/40P01 → 409 (C-05 D4). Test: reprogramación por token vs alta manual al mismo hueco → un éxito, un 409, 0×500.
- Confirmar vs cancelar del mismo turno: ambos toman `FOR UPDATE` de la fila ⇒ serializados. Test con `threading.Barrier` (spec "Confirmación concurrente con cancelación").

### D8. Auditoría

| acción | actor | `detalle` |
|---|---|---|
| `confirmar` | paciente (token) / secretaria | `{estado_anterior}` |
| `reprogramar` | paciente (token) | igual que C-05 (`exento_anticipacion` siempre `false` para paciente) |
| `cancelar` | paciente (token) | igual que C-05 |

`actor_user_id = NULL` para paciente. El no-op de reconfirmación no audita (no hubo cambio de estado; RN-GL-01 cubre creación/movimiento/cancelación).

### UI Mockups

- Design system revision: n/a
- Decision: no (sin UI; la pantalla de autogestión es C-09) — 2026-10-30
- Mockups: n/a · Approval: n/a · Preview: n/a · Visual verify: n/a

## Risks / Trade-offs

- [Token en claro en la DB] → 256 bits, índice único; hash queda como Open Question (migración 004).
- [Token en el path ⇒ aparece en access logs del servidor/proxy y en el historial del navegador] → es el diseño de RN-NO-02 (link 1-clic); la app no lo loguea; documentar en C-11 la configuración de access log.
- [Sin rate limiting en rutas públicas] → 256 bits hacen inviable la enumeración; un abuso por volumen se mitiga en C-11 (proxy). Open Question.
- [Dos UoW (resolver + operar)] → seguro por inmutabilidad del token y baja lógica (D1); un test de caracterización verifica que ninguna operación (confirmar, reprogramar, cancelar, por token o por secretaria) cambia `token_publico`.
- [Reconfirmar idempotente oculta un doble clic] → deseado para el link de WhatsApp; no audita porque no hay cambio.
- [Confirmación no toca la cola] → el worker de C-08 enviará el recordatorio igual a un turno ya confirmado salvo que filtre por estado; anotado para C-08.

## Migration Plan

1. **Sin migración de DB** (alembic sigue en `003`; `token_publico` ya es único e indexado; `accion` es texto libre). Sin variables de entorno nuevas (`CANCEL_MIN_HOURS` ya existe).
2. Deploy del backend: rutas nuevas; las existentes no cambian de contrato.
3. Rollback: revertir el commit; no hay esquema nuevo. Las auditorías `confirmar` ya escritas quedan válidas.

## Open Questions

**RESUELTAS (2026-10-30): el usuario aprobó los 9 defaults tal como están escritos; quedan como decisiones, no como preguntas abiertas.** Registro: DD-13 y DD-14 en `knowledge-base/09_decisiones_y_supuestos.md`.

1. **Rotación del token al reprogramar** — [DECIDIDO] default **no rota** (D5). Alternativa: rotar y devolver el nuevo token en el `PATCH` (rompe el link del recordatorio ya enviado).
2. **Vencimiento del token** — [DECIDIDO] default **sin TTL**; el estado y la anticipación limitan las operaciones; el `GET` funciona siempre.
3. **Hash del token en reposo** — [DECIDIDO] default **no en v1** (en claro, índice único). Alternativa: SHA-256 + migración 004 + backfill.
4. **Rate limiting de rutas por token** — [DECIDIDO] default **no en C-07** (256 bits); revisar en C-11.
5. **Campos del `GET`** — [DECIDIDO] default: horario, estado, profesional (id+nombre), tratamiento (id+nombre), `gestionable_hasta`; **sin** nombre/teléfono del paciente ni `id` del turno.
6. **Reconfirmar un `confirmado`** — [DECIDIDO] default **200 idempotente sin auditoría**. Alternativa: 422 `transicion_no_permitida`.
7. **Confirmar un turno ya iniciado** — [DECIDIDO] default **422 `anticipacion_insuficiente`** (`min_horas=0`). Confirmar dentro de la ventana de 24 h **sí** se permite.
8. **Anticipación sobre el nuevo horario al reprogramar** — [DECIDIDO] default: solo se exige sobre el horario **actual**; el nuevo solo debe ser un hueco válido y futuro.
9. **Confirmación por staff** — [DECIDIDO] default **solo `secretaria`** (`require_secretaria`), como el resto de la gestión. Alternativa: también `odontologo` (¿solo su agenda, DD-09?).
