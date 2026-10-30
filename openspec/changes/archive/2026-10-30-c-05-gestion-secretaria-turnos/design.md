# Design: c-05-gestion-secretaria-turnos

> Governance **MEDIO** (lógica de negocio). Motivación: `proposal.md` — Why. Requisitos: `specs/turnos/spec.md`. Patrón base: C-04b (D1–D6) y las skills `uow-transacciones` / `turno-use-case`. Reglas de negocio decididas por el usuario el 2026-10-30: DD-05 (secretaria exenta de anticipación), DD-06 (alta manual reusa paciente por teléfono), DD-07 (reprogramar `confirmado` → `reservado`).

## Context

Estado actual verificado en `main` (`8cdaf92`):

- `app/application/reservas.py::reservar_turno(uow_factory, datos, *, staff_id, ahora, tz) -> TurnoReservado`: UoW + DTO + `_HuecoOcupado` + `_conflicto` (huecos en UoW nueva). El turno se inserta con `TurnoRepository.insertar_si_no_solapa` (`INSERT … ON CONFLICT ON CONSTRAINT ex_turnos_sin_solape DO NOTHING RETURNING id`; `None` → 409). Siempre crea un `Paciente` nuevo. `IntegrityError` con sqlstate ≠ `23P01` se re-lanza (500). `hay_ocupacion` es de módulo y los tests lo `monkeypatch`-ean.
- `TurnoRepository.ocupados_en_rango(profesional_id, desde, hasta)` y `BloqueoRepository.ocupados_en_rango` no admiten excluir un turno.
- Migración 002: `turnos.sobreturno boolean NOT NULL DEFAULT false` **ya existe**; `ex_turnos_sin_solape … WHERE (estado <> 'cancelado' AND NOT sobreturno)`, `NOT DEFERRABLE`. ⇒ **no hace falta migración** para este change.
- `TurnoCreate` (`extra="forbid"`) rechaza `sobreturno` en la puerta pública — se mantiene.
- `turno_estados.py`: `TRANSICIONES` sin `confirmado→reservado`; `TransicionInvalidaError(ValueError)` sin mapeo HTTP.
- `app/core/exceptions.py`: no hay clases para turno inexistente, transición inválida ni anticipación.
- `RecordatorioQueue`: solo `encolar` (ZADD idempotente; un ZADD sobre un miembro existente **actualiza el score**). No hay `cancelar`.
- `Settings.CANCEL_MIN_HOURS: int = 24 (ge=0)` ya existe.
- `deps.py`: `require_secretaria` (401 sin token/ inválido, 403 otro rol) ya existe.
- `Paciente.telefono` tiene índice **no único** (`ix_pacientes_telefono`; DD-03 aceptó duplicados desde la puerta pública).

## Goals / Non-Goals

**Goals:**
- Tres casos de uso de secretaria (alta manual, reprogramar, cancelar) con el patrón C-04b, en un módulo nuevo, sin tocar el contrato de `reservar_turno`.
- Anti-solape siempre arbitrado por la base, sin 500 ni deadlocks bajo concurrencia, también en el `UPDATE` de reprogramar.
- Casos de uso parametrizados por actor, listos para que C-07 agregue la puerta por token sin reescribirlos.

**Non-Goals:**
- Puerta por token público (C-07) y confirmación (`confirmar_turno`): fuera de alcance (CHANGES.md C-05 no la lista; ver Open Questions).
- Cambiar `POST /api/turnos` (seguirá creando paciente nuevo también con JWT de secretaria).
- Mover un turno a **otro profesional** o cambiar su tratamiento/duración (v1: cancelar + alta manual).
- Unicidad de paciente por teléfono en la DB (DD-03; posible en C-11).
- Worker de recordatorios / outbox (C-08).

## Decisions

### D1. Módulo nuevo `app/application/gestion_turnos.py`, mismo patrón que `reservas.py`

- Funciones: `alta_manual_turno(uow_factory, datos: TurnoManualCreate, *, staff_id, ahora, tz) -> TurnoManualCreadoDTO`, `reprogramar_turno(uow_factory, turno_id, datos: TurnoReprogramar, *, actor: Actor, ahora, tz) -> TurnoGestionado`, `cancelar_turno(uow_factory, turno_id, *, actor: Actor, ahora) -> TurnoGestionado`.
- `Actor` = `@dataclass(frozen=True, slots=True)` con `tipo: AuditoriaActor` y `user_id: uuid.UUID | None` (secretaria: `SECRETARIA` + id; paciente en C-07: `PACIENTE` + `None`). El alta manual es solo secretaria y recibe `staff_id` (como `reservar_turno`).
- DTOs `frozen` armados dentro del `with`; el router mapea a `response_model` con `astimezone(tz)`.
- **Por qué módulo aparte**: `reservar_turno` es CRÍTICO (C-04b); mezclar la deduplicación de paciente y el sobreturno ahí cambiaría su comportamiento. Se reusan sus helpers por nombre de módulo (`reservas.hay_ocupacion`, validación de hueco) para no duplicar reglas. Los helpers privados que haga falta compartir (`_huecos_actualizados`, `_conflicto`) se generalizan a `(profesional_id, dia, tratamiento_id)` de forma **aditiva** (el llamador actual no cambia su resultado; lo cubren los tests de C-04/C-04b).
- Alternativa descartada: extender `reservar_turno` con flags `sobreturno`/`reusar_paciente` — cambia un contrato CRÍTICO y acopla dos puertas con reglas distintas.

### D2. Alta manual: deduplicación de paciente y `insertar_si_no_solapa` con `sobreturno`

- `PacienteRepository.buscar_por_telefono(telefono) -> Paciente | None`: `WHERE telefono = :t AND is_active ORDER BY created_at, id LIMIT 1` (usa `ix_pacientes_telefono`). "Normalizado" = el valor ya validado E.164 por `TelefonoE164` con `str_strip_whitespace` (la regex no admite espacios ni guiones, así que hay una única forma canónica). Si existe se reutiliza **sin modificar** su nombre (evita que un error de tipeo pise datos); si no, se crea.
- `TurnoRepository.insertar_si_no_solapa(..., sobreturno: bool = False)`: kwarg nuevo con default ⇒ la reserva no cambia. Con `sobreturno=True` la fila queda fuera del `WHERE` de la exclusión, así que nunca conflictúa.
- Flujo dentro de `with`: validar (404/422 reusando la validación de `reservas`) → advisory lock (D4) → si `not sobreturno`: `hay_ocupacion` (turnos + bloqueos) → si `sobreturno`: solo bloqueos (D3) → paciente (buscar o crear + flush) → `insertar_si_no_solapa` (`None` → `_HuecoOcupado`) → `AuditoriaTurno(accion="crear", detalle={origen, sobreturno, paciente_reutilizado})` → `flush()` → DTO.
- Un 409 hace rollback de todo el `with` ⇒ un paciente recién creado no queda (spec "Inserción condicional sin fila no deja residuos").

### D3. Sobreturno: marca explícita, solo secretaria, nunca sobre bloqueos

- Entrada: `TurnoManualCreate.sobreturno: bool = False` y `TurnoReprogramar.sobreturno: bool = False` (ambos `extra="forbid"`). `TurnoCreate` sigue sin el campo (422 en la puerta pública).
- Doble control de rol: los endpoints usan `require_secretaria`; además `reprogramar_turno` rechaza `sobreturno=True` con un actor que no sea `SECRETARIA` lanzando un `ValueError` interno (defensa en profundidad para C-07, cuya puerta token no expondrá el campo: inalcanzable por HTTP, cubierto con un test de aplicación). No se agrega una clase `AppError` para un caso que la API no puede producir.
- Con la marca se omite **solo** la ocupación por turnos; `BloqueoRepository.ocupados_en_rango` se sigue chequeando (un bloqueo = el profesional no está) y `es_inicio_valido` (grilla, franja, futuro) también.
- El sobreturno sigue ocupando la disponibilidad (`ocupados_en_rango` no filtra por `sobreturno`; spec `agenda` sin cambios): el hueco ya estaba ocupado o queda ocupado.
- Auditoría con `sobreturno: true`. En reprogramar, el valor del body **reemplaza** el del turno (mover un sobreturno a un hueco libre sin marca lo normaliza).

### D4. Concurrencia del `UPDATE`: advisory lock por profesional + 23P01/40P01 → 409

- Problema: reprogramar es un `UPDATE`; `ON CONFLICT` no aplica. Dos `UPDATE` solapados concurrentes pueden deadlockear al verificar la exclusión (cada uno espera la tupla no confirmada del otro) ⇒ `40P01`, que hoy `reservas.py` re-lanza como 500.
- Decisión: dentro de la UoW, **antes** de `hay_ocupacion`, `SELECT pg_advisory_xact_lock(hashtext(:profesional_id::text))` (`TurnoRepository.bloquear_agenda(profesional_id)`). Serializa todas las escrituras de secretaria que ocupan agenda de ese profesional (reprogramar y alta manual); se libera solo al commit/rollback (sin riesgo de lock colgado). Con el lock, el chequeo de aplicación ve el estado confirmado del ganador ⇒ el perdedor recibe 409 limpio con huecos.
- Orden de locks (evita ciclos): (1) `SELECT profesional_id` del turno sin lock (404 si no existe), (2) advisory lock del profesional, (3) `SELECT … FOR UPDATE` del turno (relectura con estado vigente; serializa reprogramar vs cancelar del mismo turno), (4) validaciones + `UPDATE` + auditoría + `flush()`. Cancelar solo toma (3) (libera agenda, no la ocupa) — no hay ciclo porque nunca se pide el advisory lock teniendo un row lock de otro profesional.
- Colisiones de `hashtext` (32 bits) entre profesionales solo causan serialización extra, nunca incorrección.
- **Red de seguridad**: la exclusión sigue siendo el árbitro. `IntegrityError` `23P01` → `_conflicto` (409 con huecos leídos en UoW nueva). `OperationalError`/`DBAPIError` con sqlstate `40P01` en reprogramar → 409 también (residual: carrera con la reserva pública, que no toma el lock porque `reservar_turno` es CRÍTICO y no se toca), con `logger.warning`. Cualquier otro sqlstate se re-lanza (500).
- Alternativas: (a) `SERIALIZABLE` + reintento — más cambios en la UoW (CRÍTICO) y reintentos opacos; (b) `SELECT … FOR UPDATE` de los turnos del rango — no bloquea huecos vacíos (phantom); (c) solo mapear 40P01 → 409 sin lock — el perdedor recibiría huecos posiblemente desactualizados y el deadlock cuesta un timeout del detector (`deadlock_timeout`, 1 s). El lock es la opción más simple y determinística.
- Tests (`threading.Barrier`, `TestClient` por hilo, como `test_turnos_concurrencia.py`): 2 reprogramaciones al mismo hueco; reprogramación + alta pública; reprogramación + alta manual; reprogramaciones cruzadas; N altas manuales simultáneas. Además un test que, con `hay_ocupacion` stub a `False`, fuerza la vía de la constraint (23P01 → 409) en reprogramar.

### D5. `excluir_turno_id` en la ocupación

- `TurnoRepository.ocupados_en_rango(profesional_id, desde, hasta, *, excluir_turno_id: uuid.UUID | None = None)` agrega `Turno.id != excluir_turno_id` cuando no es `None`. `reservas.hay_ocupacion(session, profesional_id, inicio, fin, *, excluir_turno_id=None)` lo propaga solo a turnos. Kwargs con default ⇒ `reservar_turno` y el `monkeypatch` existente no cambian.
- La exclusión de la base no necesita nada: al hacer `UPDATE`, Postgres no compara la nueva versión de la fila contra la versión vieja de la misma fila.

### D6. Estados: reprogramar como regla propia, no como transición general

- `turno_estados.py` agrega `estado_tras_reprogramar(actual) -> EstadoTurno`: `RESERVADO`/`CONFIRMADO` → `RESERVADO`; terminal → `TransicionInvalidaError(actual, RESERVADO)`. `TRANSICIONES` **no** gana `confirmado→reservado`: así nadie puede "desconfirmar" un turno sin moverlo (DD-07 se cumple en el único lugar donde aplica).
- Cancelar usa `transicionar(actual, CANCELADO)`.
- El caso de uso convierte `TransicionInvalidaError` en `TransicionNoPermitidaError` (422) — el dominio sigue sin depender de HTTP.

### D7. Anticipación por actor: regla pura de dominio

- `app/domain/anticipacion.py::verificar_anticipacion(inicio_actual, ahora, *, actor_tipo, min_horas) -> bool` (devuelve si hubo exención) o lanza `AnticipacionInsuficienteError` (vía el caso de uso). Paciente: exige `inicio_actual - ahora >= timedelta(hours=min_horas)`. Secretaria: exige solo `inicio_actual > ahora`; devuelve `exento=True` si el turno cae dentro de la ventana de paciente (para auditar `exento_anticipacion`).
- `min_horas = get_settings().CANCEL_MIN_HOURS` (nunca hardcode); `ahora` inyectado (`get_ahora`) ⇒ tests deterministas.
- Se aplica al `inicio` **actual** del turno (lo que se protege es el horario que se libera), antes de revalidar el nuevo hueco.
- En C-05 la rama paciente es alcanzable solo desde el caso de uso (tests de aplicación); por HTTP, el 422 de C-05 es el de "turno ya iniciado".

### D8. Errores nuevos (`app/core/exceptions.py`)

- `TurnoNoEncontradoError(NotFoundError)`: 404, `code="turno_no_encontrado"`. El mismo se usará en C-07 para token inválido (sin datos del turno).
- `TransicionNoPermitidaError(AppError)`: 422, `code="transicion_no_permitida"`, `extra()` con `estado_actual`.
- `AnticipacionInsuficienteError(AppError)`: 422, `code="anticipacion_insuficiente"`, `extra()` con `min_horas`.
- `HuecoOcupadoError` e `InicioInvalidoError` se reusan tal cual.

### D9. Endpoints y schemas (`app/api/turnos.py`, `app/domain/schemas.py`)

| Método y ruta | Auth | Body | 2xx | Errores |
|---|---|---|---|---|
| `POST /api/turnos/manual` | `require_secretaria` | `TurnoManualCreate` | 201 `TurnoManualCreado` | 401/403/404/409/422 |
| `PATCH /api/turnos/{turno_id}` | `require_secretaria` | `TurnoReprogramar` | 200 `TurnoGestionadoOut` | 401/403/404/409/422 |
| `DELETE /api/turnos/{turno_id}` | `require_secretaria` | — | 200 `TurnoGestionadoOut` | 401/403/404/422 |

- `TurnoManualCreate`: campos de `TurnoCreate` + `sobreturno: bool = False`, `extra="forbid"`, `str_strip_whitespace`.
- `TurnoReprogramar`: `inicio: AwareDatetime`, `sobreturno: bool = False`, `extra="forbid"`.
- `TurnoManualCreado`: `TurnoCreado` + `paciente_id`, `sobreturno`, con `origen: Literal["secretaria"]`; mantiene `token_publico` (es una creación).
- `TurnoGestionadoOut`: `id, profesional_id, paciente_id, tratamiento_id, inicio, fin, estado: Literal[todos los estados], origen, sobreturno`, `extra="forbid"`, **sin** `token_publico`.
- `turno_id: Annotated[uuid.UUID, Path()]` (UUID inválido → 422 de FastAPI). Todo `def`. `DELETE` devuelve 200 con cuerpo (la SPA de C-10 lo usa para refrescar sin otra lectura).
- `/manual` se declara antes de `/{turno_id}` (no colisionan por método, pero se deja explícito).

### D10. Efectos post-commit en el router

- `RecordatorioQueue.cancelar(turno_id) -> bool`: `ZREM` con el mismo reintento/backoff que `encolar`; nunca lanza; `logger.warning` si falla.
- Reprogramar: `cola.encolar(dto.id, dto.inicio)` (ZADD actualiza el score del miembro existente ⇒ "re-encolar" sin ZREM previo, sin ventana sin job). Cancelar: `cola.cancelar(dto.id)`. Alta manual: `cola.encolar` como la reserva.
- Todos después del retorno del caso de uso (ya hubo commit), nunca dentro del request hacia WhatsApp. Con tres operaciones y un efecto cada una, se mantiene en el router (C-04b D3); si C-07 suma efectos, extraer orquestador.

### D11. Auditoría

| acción | `detalle` |
|---|---|
| `crear` (manual) | `{origen: "secretaria", sobreturno, paciente_reutilizado}` |
| `reprogramar` | `{inicio_anterior, fin_anterior, inicio_nuevo, fin_nuevo, estado_anterior, estado_nuevo, sobreturno, exento_anticipacion}` (instantes ISO 8601 UTC) |
| `cancelar` | `{estado_anterior, exento_anticipacion}` |

`actor_tipo`/`actor_user_id` desde `Actor`. Misma transacción; rollback ⇒ sin auditoría.

### UI Mockups

- Design system revision: n/a
- Decision: no (no UI; la agenda es C-10) — 2026-10-30
- Mockups: n/a · Approval: n/a · Preview: n/a · Visual verify: n/a

## Risks / Trade-offs

- [Carrera reserva pública vs reprogramación: la pública no toma el advisory lock] → la exclusión sigue arbitrando; 23P01 y 40P01 → 409 en reprogramar; test de concurrencia mixto. Si apareciera 40P01 en la reserva pública, se resuelve en un change CRÍTICO aparte.
- [Pacientes duplicados por dos altas manuales simultáneas con el mismo teléfono nuevo] → no hay unicidad en la DB (DD-03); ventana mínima; aceptado y anotado para C-11 (unique parcial o advisory lock por teléfono).
- [DD-06 unifica personas que comparten teléfono (familia)] → trade-off aceptado por el usuario; el nombre del paciente reutilizado no se pisa y la auditoría marca `paciente_reutilizado`.
- [Secretaria sin freno de anticipación] → DD-05; auditoría con `exento_anticipacion`.
- [Advisory lock serializa altas/reprogramaciones de secretaria del mismo profesional] → transacciones cortas (milisegundos); impacto despreciable para una clínica.
- [Los `huecos` del 409 de reprogramar cuentan al propio turno como ocupado] → la secretaria ve su horario actual como no disponible, que es correcto para "a dónde lo muevo".
- [Pérdida de job entre commit y efecto Redis] → igual que C-04 (reconciliación en C-08).

## Migration Plan

1. **Sin migración de DB** (alembic sigue en `002`; `sobreturno` y la exclusión parcial ya existen). Sin variables de entorno nuevas (`CANCEL_MIN_HOURS` ya está).
2. Deploy del backend: endpoints nuevos; `POST /api/turnos` byte a byte igual.
3. Rollback: revertir el commit; no hay esquema nuevo. Los turnos con `sobreturno=true` creados quedan válidos para la 002.

## Open Questions

Resueltas con el usuario (2026-10-30):

- **Confirmar por secretaria/odontólogo** (`POST /api/turnos/{id}/confirmar`): **DECIDIDO — fuera de C-05, va en C-07** (mismo caso de uso que la puerta token).
- **`POST /api/turnos` con JWT de secretaria**: **DECIDIDO — no se toca** `reservar_turno` (CRÍTICO); sigue sin deduplicar. La secretaria usa `/manual`, que reusa paciente por teléfono (DD-06).
- **Sobreturno fuera de grilla**: **DECIDIDO — el sobreturno respeta grilla y franja**; solo exime del chequeo de solape. Nunca saltea bloqueos.
- **Mover a otro profesional** en el `PATCH`: fuera de alcance v1 (cancelar + alta manual).
