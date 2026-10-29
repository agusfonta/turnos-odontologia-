---
name: uow-transacciones
description: Contrato unico de transacciones del backend (UnitOfWork). Usar al escribir o modificar cualquier caso de uso en app/application/ que persista datos, un router que lo invoque, efectos post-commit (Redis/WhatsApp), manejo de IntegrityError/409 por solape, o tests de atomicidad. Obligatoria en C-05, C-07 y en todo change que escriba en la DB.
---

# uow-transacciones

Contrato vigente tras C-04b. Implementacion de referencia: `src/backend/app/application/reservas.py` (`reservar_turno`). Copiala; no inventes otra forma.

> Gobernanza: tocar este contrato (`app/infrastructure/unit_of_work.py`, la firma o el flujo de `reservar_turno`) es CRITICO/HIGH: describir el cambio y esperar aprobacion humana antes de escribir. Usarlo en un caso de uso nuevo es MEDIO.

## 1. Quien es dueño de la transaccion

- El caso de uso recibe `uow_factory: UowFactory` (dependencia FastAPI `get_uow_factory`), NUNCA una `Session` de `get_db` para escribir.
- NUNCA llama `commit()`/`rollback()`. Solo el bloque `with` cierra: commit en salida limpia, rollback ante excepcion (`UnitOfWork.__exit__`).

```python
def reservar_turno(uow_factory: UowFactory, datos, *, staff_id, ahora, tz) -> TurnoReservado:
    try:
        with uow_factory() as session:
            ...
```

## 2. Retornar datos planos

- Armar un DTO (`@dataclass(frozen=True, slots=True)`, ej. `TurnoReservado`) DENTRO del `with`, despues de un `flush()` final. Nunca devolver entidades ORM: la sesion se cierra al salir.
- El `flush()` final hace que todo error de datos salga antes del COMMIT de `__exit__`.

```python
            session.flush()  # todo error de datos sale aca, antes del COMMIT de __exit__
            reservado = TurnoReservado(id=turno.id, ..., token_publico=token_publico)
    ...
    return reservado
```

## 3. Efectos externos solo despues del retorno

Redis, WhatsApp o cualquier cosa fuera de la DB se dispara en el router/orquestador cuando el caso de uso ya retorno (= hubo commit). Una excepcion del caso de uso sale antes del efecto, asi nunca se encola sin commit. Un fallo de encolado jamas rompe el request (`RecordatorioQueue.encolar` reintenta y no lanza).

```python
reservado = reservar_turno(uow_factory, datos, staff_id=..., ahora=ahora, tz=tz)
cola.encolar(reservado.id, reservado.inicio)  # post-commit; nunca lanza
```

## 4. Conflictos (23P01) y ocupacion

- El `try/except IntegrityError` envuelve el `with` COMPLETO (cubre tambien un fallo en el COMMIT).
- sqlstate `23P01` (exclusion violation) -> 409 via `_conflicto`; cualquier otro sqlstate se re-lanza (500). Nunca enmascarar como 409.
- La constraint `ex_turnos_sin_solape` NO es diferible: el error aparece en el `flush()` del INSERT/UPDATE, no al commit. Por eso el flush final es obligatorio.
- El chequeo de aplicacion (`hay_ocupacion`) lanza una excepcion interna (`_HuecoOcupado`) que se convierte FUERA del `with`.
- Los `huecos` del 409 se releen en una UoW NUEVA (`_conflicto`), una vez que la fallida hizo rollback y close. Nunca con la sesion fallida.

```python
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != EXCLUSION_VIOLATION:
            raise
        raise _conflicto(uow_factory, datos, ahora=ahora, tz=tz) from exc
    except _HuecoOcupado:
        raise _conflicto(uow_factory, datos, ahora=ahora, tz=tz) from None
```

## 5. Estilo

- Todo `def` sincrono (regla dura del proyecto; `async` solo si todo es no bloqueante).
- Helpers a nivel modulo llamados por nombre (`hay_ocupacion`, `_conflicto`) para que los tests puedan `monkeypatch.setattr("app.application.<modulo>.hay_ocupacion", ...)`. No inlinearlos ni importarlos con alias.

## 6. Tests obligatorios (reusar `tests/support.py`, no re-describirlo)

- `tests/test_transacciones_arquitectura.py` (guarda AST: ni `app/application` ni `app/api` llaman `.commit()`/`.rollback()`) debe seguir verde.
- Espia de orden con `factoria_espia(engine, bitacora, commit_error=...)`: exito `["enter","commit","close"]`; fallo de escritura + relectura `["enter","rollback","close","enter","commit","close"]` (ver `BITACORA_CONFLICTO` en `tests/test_reservas_uow.py`).
- Sin filas tras un fallo (404/409/422/500, incl. fallo de COMMIT), leyendo desde OTRA sesion (`mig_session.expire_all()`), y sin job encolado (`zcard` del fakeredis).
- Orden commit -> encolado; otro sqlstate no se enmascara (`_pg_error`).
- Si toca agenda: test de concurrencia con `threading.Barrier` contra Postgres real (patron `tests/test_turnos_concurrencia.py`; un `TestClient` por hilo).
- `entorno_api`/`api_client` en `tests/conftest.py` pisa `get_uow_factory` hacia la DB clonada; los tests de API de escritura deben usarlo.

## 7. Anti-patrones

- `commit`/`rollback` en un caso de uso o router.
- Devolver una entidad ORM (o usarla despues del `with`).
- Encolar/enviar dentro del `with`.
- Releer huecos con la sesion fallida.
- `Session(...)`/`SessionLocal()` ad hoc o escribir con `get_db`.
- Validar solape solo en la app (la constraint de Postgres es la garantia).
- `async def` con llamadas bloqueantes.
