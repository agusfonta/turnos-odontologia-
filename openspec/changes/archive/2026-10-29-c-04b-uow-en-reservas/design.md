# Design: c-04b-uow-en-reservas

> Governance **CRÍTICO** (reserva, anti-solape, auditoría). Refactor que preserva comportamiento. Motivación: ver `proposal.md` — Why. Requisitos: `specs/turnos/spec.md`.

## Context

Estado actual (verificado en el código de `main`, commit `893ce61`):

- `app/infrastructure/unit_of_work.py`: `UnitOfWork(session_factory=SessionLocal)`, context manager síncrono. `__enter__` crea y devuelve una `Session`; `__exit__` hace `commit()` si no hubo excepción, si no `rollback()`; siempre `close()` y `self.session = None`. Ya testeada en `tests/test_repositories.py` con `session_factory` inyectada. Hoy **no la usa nadie** en `app/`.
- `app/application/reservas.py::reservar_turno(session, datos, *, staff, ahora, tz) -> Turno`: recibe la `Session` de `get_db`, hace `session.commit()` y, en `_conflicto`, `session.rollback()` + relectura de huecos con la **misma** sesión. Devuelve la entidad ORM.
- `app/api/turnos.py::crear_turno`: llama al caso de uso, luego `cola.encolar(turno.id, turno.inicio)` y arma `TurnoCreado` leyendo atributos ORM **después del commit** (con `expire_on_commit=True` eso dispara un `SELECT` de refresco implícito).
- `get_optional_staff` (`app/api/deps.py`) resuelve el `User` staff con su propia dependencia `get_db`.
- Constraint de la migración 002: `ALTER TABLE turnos ADD CONSTRAINT ex_turnos_sin_solape EXCLUDE USING gist (...) WHERE (...)` **sin cláusula `DEFERRABLE`** ⇒ es `NOT DEFERRABLE INITIALLY IMMEDIATE`: se verifica al ejecutar cada `INSERT`, es decir en el `flush()` que inserta el `Turno`, no en el `COMMIT`.
- Tests de C-04 que deben quedar verdes sin tocar sus aserciones: `test_api_turnos.py` (incluye `test_rama_exclusion_23p01_tambien_da_409`, que hace `monkeypatch` de `app.application.reservas.hay_ocupacion`), `test_turnos_concurrencia.py` (Barrier 2 y 5 hilos, con y sin chequeo de app), `test_recordatorio_queue.py`, `test_repositories.py`. La fixture `api_client` (conftest) hoy solo pisa `get_db` y `get_recordatorio_queue`.

## Goals / Non-Goals

**Goals:**
- Un único dueño de la transacción de escritura: el bloque `with UnitOfWork`. Los casos de uso nunca llaman `commit`/`rollback`.
- Ningún objeto ORM cruza el límite de la transacción hacia el router.
- Efectos externos (Redis) estrictamente después del commit.
- Patrón documentado y copiable por C-05 (mover/cancelar/sobreturno) y C-07 (confirmar/cancelar/reprogramar por token).

**Non-Goals:**
- Migrar los endpoints de solo lectura (`disponibilidad`, `profesionales`, `tratamientos`) ni `auth`/`deps` a la UoW: siguen con `get_db` (lecturas sin commit; no tienen transacción que poseer).
- Cambiar la semántica de `UnitOfWork` (commit/rollback/close), el nivel de aislamiento, la constraint o cualquier esquema. **Sin migración de DB.**
- Outbox transaccional para el recordatorio (sigue la Decisión 9 de C-04; reconciliación en C-08).
- Cambios de contrato HTTP (status, cuerpos, headers).

## Decisions

### D1. El caso de uso recibe una **factoría** de UoW, provista por una dependencia FastAPI

- `app/infrastructure/unit_of_work.py` agrega `UowFactory = Callable[[], UnitOfWork]` y la dependencia `get_uow_factory() -> UowFactory` que devuelve `UnitOfWork` (usa `SessionLocal` por defecto).
- Firma nueva: `reservar_turno(uow_factory: UowFactory, datos: TurnoCreate, *, staff_id: uuid.UUID | None, ahora: datetime, tz: ZoneInfo) -> TurnoReservado`.
- El router declara `UowDep = Annotated[UowFactory, Depends(get_uow_factory)]` y deja de inyectar `get_db` para la reserva.
- Tests: la fixture `api_client` agrega `app.dependency_overrides[get_uow_factory] = lambda: (lambda: UnitOfWork(session_factory=lambda: Session(mig_engine)))`. Es la misma inyección de `session_factory` que ya usa `test_repositories.py`. La concurrencia (`TestClient` por hilo sobre la misma `app`) hereda el override.
- **Por qué factoría y no instancia**: el camino 409 necesita una **segunda** UoW, fresca, después de cerrar la fallida (D4). Con factoría eso es explícito (`with uow_factory()` dos veces) y no reutiliza un objeto con estado mutable (`self.session`). C-05/C-07 harán lo mismo cuando necesiten releer tras un rollback.
- **Por qué `staff_id` en vez de `User`**: el `User` lo carga `get_optional_staff` en **otra** sesión (`get_db`); pasar solo el id evita que una entidad ORM de una sesión ajena entre al caso de uso. El caso de uso deriva `origen`/`actor_tipo` de `staff_id is not None` (mismo criterio que hoy con `staff is not None`).
- Alternativas: (a) dependencia que hace `yield` de una `Session` dentro de un `with UnitOfWork` ("UoW por request") — descartada: el commit ocurriría al cerrar la dependencia, **después** de que el router ya encoló y armó la respuesta; rompe "efectos post-commit" y el 409 del commit tardío no se podría mapear. (b) `UnitOfWork` instanciada dentro del caso de uso con `SessionLocal` fijo — descartada: los tests no podrían apuntar a la DB clonada.

### D2. El caso de uso devuelve un DTO de aplicación, no la entidad ORM

- `@dataclass(frozen=True, slots=True) class TurnoReservado` en `app/application/reservas.py` con: `id: uuid.UUID`, `profesional_id: uuid.UUID`, `tratamiento_id: int | None`, `inicio: datetime`, `fin: datetime`, `origen: str` (`"online" | "secretaria"`), `token_publico: str`.
- Se construye **dentro** del `with`, después del `flush()` final (D4) y antes de salir, a partir de valores ya en memoria (el `id` lo genera Python, `default=uuid.uuid4`; `inicio`/`fin` son los valores aware asignados). No requiere relectura de la DB.
- El router mapea `TurnoReservado → TurnoCreado` aplicando `astimezone(tz)` a `inicio`/`fin` y `estado="reservado"`. El contrato `TurnoCreado` (Pydantic, `extra="forbid"`) no cambia.
- **Por qué dataclass y no Pydantic**: es un objeto interno ya validado (no entra input externo); `TurnoCreado` sigue siendo el único contrato HTTP. Devolver `TurnoCreado` desde aplicación acoplaría la capa de aplicación al esquema HTTP.
- Diferencia sutil vs. hoy: hoy `inicio`/`fin` de la respuesta salen de un refresco post-commit (valor leído de Postgres); ahora salen del valor en memoria. Es el mismo instante (`timestamptz` no pierde precisión de microsegundos) y `astimezone(tz)` normaliza el offset ⇒ mismo JSON. Lo cubre `test_inicio_en_utc_se_acepta_y_vuelve_con_offset_de_clinica`.

### D3. Efectos externos en el router, después de que el caso de uso retornó

- Patrón: **el caso de uso es el límite de la transacción** (retorna ⇒ ya hubo commit); **el router ejecuta los efectos externos** con el DTO: `reservado = reservar_turno(...)` → `cola.encolar(reservado.id, reservado.inicio)` → `return TurnoCreado(...)`.
- Cualquier excepción del caso de uso (404/422/409/500, o falla de commit) sale antes de la línea del encolado ⇒ nunca se encola sin commit.
- **Por qué el router y no una función orquestadora de aplicación** (`reservar_y_encolar`): hoy hay un único efecto, ya inyectado como dependencia (`ColaDep`) y tolerante a fallas; una capa más agrega indirección sin beneficio. Si C-05/C-07 acumulan varios efectos por operación (p.ej. reencolar + desencolar), se extrae entonces. Trade-off anotado en Risks.
- Patrón para C-05/C-07 (se documenta en el docstring del módulo `reservas.py`): `def caso_de_uso(uow_factory, ..., ) -> DTO` con `with uow_factory() as session:` adentro, sin `commit`/`rollback`, DTO armado dentro del `with`; efectos externos en el router con el DTO.

### D4. Manejo de 23P01: `flush()` explícito dentro del `with`; huecos con UoW nueva fuera

Estructura del caso de uso:

```
try:
    with uow_factory() as session:
        validar (404/422) ...
        if hay_ocupacion(session, ...):  raise _HuecoOcupado()      # señal interna
        insertar Paciente → flush; Turno → flush (aquí salta 23P01); AuditoriaTurno
        session.flush()                    # flush final: todo error de DB sale acá
        reservado = TurnoReservado(...)
except IntegrityError as exc:
    if sqlstate(exc) != "23P01": raise     # 500, igual que hoy
    raise _conflicto(uow_factory, datos, ahora=ahora, tz=tz) from exc
except _HuecoOcupado:
    raise _conflicto(uow_factory, datos, ahora=ahora, tz=tz) from None
return reservado
```

- La excepción atraviesa el `with` ⇒ `__exit__` hace `rollback()` + `close()` de la transacción fallida. Recién **después**, `_conflicto` abre `with uow_factory() as lectura:` (UoW nueva, solo lectura; su commit es un no-op) y calcula `HuecoOcupadoError(huecos)` con `_huecos_actualizados`. Mismo cuerpo 409 que hoy (`{detail, code:"hueco_ocupado", huecos:[...]}`).
- **¿Alcanza con `flush()`? Sí**, porque `ex_turnos_sin_solape` es `NOT DEFERRABLE` (verificado en `alembic/versions/002_turnos_bloqueos_auditoria.py`): Postgres la evalúa en el `INSERT` del `Turno`, que se ejecuta en el `flush()`. Ante una carrera, el `INSERT` del perdedor espera la tupla no confirmada del ganador y, cuando éste confirma, falla con 23P01 **en el flush**, dentro del `with`. El `flush()` final asegura además que el `INSERT` de auditoría (y cualquier otra violación, p.ej. FK) también ocurra antes de salir del `with`, de modo que el `COMMIT` de `__exit__` solo pueda fallar por causas no relacionadas a datos (conexión).
- **Defensa en profundidad**: el `try/except IntegrityError` envuelve el `with` completo, no solo el `flush`. Si en el futuro alguien declarara la constraint `DEFERRABLE INITIALLY DEFERRED`, el 23P01 saldría del `commit()` en `__exit__` y seguiría mapeándose a 409. Un test lo fija con una UoW de test cuyo `commit` lanza un `IntegrityError` 23P01 sintético (no requiere migración).
- **Por qué una UoW nueva para los huecos**: tras un error de flush la sesión queda en estado "transaction rolled back due to previous exception"; releer requiere cerrar esa transacción. Hacerlo con una UoW nueva, después de que la fallida se cerró, garantiza (a) cero datos parciales del perdedor y (b) una lectura `READ COMMITTED` nueva que ve al ganador.
- **El camino del chequeo de aplicación** (`hay_ocupacion` = True) también usa una UoW nueva para los huecos (señal interna `_HuecoOcupado`), para tener un único camino de armado del 409. Costo: un checkout extra del pool en un 409 — aceptado. Se mantiene el nombre `hay_ocupacion` a nivel de módulo `app.application.reservas` porque los tests de C-04 lo `monkeypatch`-ean.

### D5. `UnitOfWork` no cambia de semántica

- No se modifica `__enter__`/`__exit__`. Si `commit()` en `__exit__` lanza, `finally: close()` libera la conexión y Postgres descarta la transacción (SQLAlchemy ya hizo rollback interno del commit fallido). Un test de atomicidad lo fija (falla de commit ⇒ sin filas).
- Solo se agregan `UowFactory` y `get_uow_factory` (D1).

### D6. Guardas de regresión

- **Chequeo estático (AST, no grep)**: `tests/test_transacciones_arquitectura.py` recorre `app/application/**/*.py` y `app/api/**/*.py`, parsea con `ast` y falla si existe una llamada `X.commit()` o `X.rollback()`. AST evita falsos positivos en comentarios/docstrings. Fuera de alcance: `infrastructure/` (la UoW y el seed CLI son legítimos).
- **Orden commit → encolado**: test de API con una UoW espía (subclase de `UnitOfWork` que registra `"commit"` en una lista compartida) y una cola fake que registra `"encolar"` y, al encolar, verifica con **otra** conexión que el turno ya existe. Esperado: `["commit", "encolar"]`.
- **Atomicidad**: UoW de test cuyo `commit` lanza `OperationalError` sintético ⇒ respuesta 500, cero paciente/turno/auditoría, cola sin jobs.
- **Carrera**: se reutilizan los tests de `test_turnos_concurrencia.py` y se agrega aserción de huecos actualizados en el 409 (el horario ganado no figura).

### UI Mockups

- Design system revision: n/a
- Decision: no (no UI) — 2026-10-29
- Mockups: n/a · Approval: n/a · Preview: n/a · Visual verify: n/a

## Risks / Trade-offs

- [Refactor en dominio CRÍTICO rompe anti-solape o auditoría] → la garantía sigue siendo la constraint de DB (no se toca); safety net completo antes de empezar; los tests de C-04 no cambian sus aserciones; concurrencia real con Barrier corre en cada task que toque el caso de uso.
- [Override de tests desalineado: la reserva usa la UoW pero `api_client` solo pisa `get_db`] → la primera task (RED) agrega el override de `get_uow_factory` en `conftest.py`; sin él, los tests de reserva apuntarían a `SessionLocal` (DB de `DATABASE_URL`) y fallarían visiblemente, nunca en silencio.
- [Dos conexiones por request de secretaria] (`get_db` para el staff + UoW para la escritura) → impacto despreciable en el tamaño de pool actual; si C-11 lo necesita, el staff puede resolverse por claims del JWT.
- [Respuesta armada con valores en memoria en vez de refresco de DB] → mismo instante; cubierto por tests de offset. Si en el futuro se agregan columnas con `server_default` a la respuesta (p.ej. `created_at`), deben leerse **dentro** del `with` tras el `flush` (con `RETURNING`/`refresh`), nunca después.
- [Router como lugar de los efectos] → si C-05/C-07 acumulan efectos múltiples, extraer un orquestador de aplicación post-commit; anotado en D3.
- [Pérdida del job si el proceso muere entre commit y encolado] → igual que hoy (Decisión 9 de C-04); reconciliación pendiente en C-08.
- [Monkeypatch de `hay_ocupacion` en tests existentes] → el símbolo se conserva en `app.application.reservas` y se invoca por nombre de módulo (no capturado en un closure) para que el monkeypatch siga surtiendo efecto.

## Migration Plan

1. **Sin migración de DB** (alembic queda en `002`). Sin variables de entorno nuevas. Sin cambios de frontend.
2. Deploy del backend: el endpoint es compatible byte a byte.
3. Rollback: revertir el commit del change; no hay estado persistido nuevo.

## Open Questions

- Ninguna que bloquee. (A confirmar por el usuario solo si quiere otra cosa: efectos en router vs. orquestador de aplicación — D3 elige router.)
