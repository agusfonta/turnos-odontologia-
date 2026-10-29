# Proposal: c-04b-uow-en-reservas

> Governance: **CRÍTICO** (toca el caso de uso de reserva de C-04: anti-solape, auditoría, recordatorio). Refactor que **preserva comportamiento**: sin cambio de contrato HTTP, sin migración de DB.

## Why

El caso de uso `reservar_turno` (C-04) recibe una `Session` de `get_db` y hace `commit()`/`rollback()` por su cuenta, devuelve la entidad ORM `Turno` y el router lee sus atributos después del commit. La `UnitOfWork` de C-02 existe pero no se usa. C-05 (gestión de secretaria) y C-07 (autogestión por token) van a copiar este patrón para mover, cancelar y reprogramar turnos; si se construyen sobre el patrón actual, la propiedad de la transacción queda dispersa en cada caso de uso. Este change corto (camino "A", decidido por el usuario) fija el patrón correcto **antes** de C-05/C-07.

## What Changes

- El caso de uso de reserva deja de llamar `commit`/`rollback`: la transacción la abre y la cierra exclusivamente un bloque `with UnitOfWork`, obtenido de una factoría inyectada como dependencia de FastAPI (sustituible en tests).
- El caso de uso devuelve un DTO inmutable de aplicación (`TurnoReservado`) con los datos que necesita la respuesta `TurnoCreado` y el encolado, en vez de la entidad ORM; el router ya no lee ORM después del commit.
- El encolado del recordatorio (`RecordatorioQueue.encolar`) se ejecuta solo después de que el `with` terminó con commit exitoso; nunca ante 404/422/409/500 ni ante un commit fallido. Se documenta como el patrón que copian C-05/C-07.
- El conflicto por exclusion constraint (sqlstate `23P01`) sigue respondiendo 409 `hueco_ocupado` con huecos actualizados; los huecos se recalculan con una `UnitOfWork` nueva, después de cerrada (rollback) la transacción fallida. Otras `IntegrityError` siguen siendo 500.
- Se agregan tests de guarda: ningún módulo de `app/application` ni `app/api` llama `commit`/`rollback` (chequeo estático por AST); atomicidad (fallo ⇒ sin filas de paciente/turno/auditoría); carrera real 201/409 con huecos actualizados; encolado solo post-commit.
- Tarea final: registrar `C-04b` en `CHANGES.md` como prerrequisito de C-05 y C-07.
- **Sin migración de DB** (la constraint `ex_turnos_sin_solape` de la 002 no cambia). **Sin cambios de API** (mismos status, cuerpos y headers).

## Capabilities

### New Capabilities
- Ninguna.

### Modified Capabilities
- `turnos`: se explicita a nivel de requisito la atomicidad de la reserva (paciente + turno + auditoría todo-o-nada) y que el recordatorio se encola solo tras la confirmación (commit) de la transacción; el 409 por carrera se arma después de cerrada la transacción fallida. Las respuestas observables no cambian.

## Impact

- **Código**: `src/backend/app/application/reservas.py` (firma y transacción), `src/backend/app/api/turnos.py` (dependencia UoW, mapeo DTO→`TurnoCreado`, encolado post-commit), `src/backend/app/infrastructure/unit_of_work.py` (dependencia/factoría para FastAPI; la clase no cambia de semántica), `src/backend/tests/conftest.py` (override de la factoría a la DB clonada).
- **Tests**: los de C-04 (`test_api_turnos.py`, `test_turnos_concurrencia.py`, `test_recordatorio_queue.py`, `test_repositories.py`) deben seguir verdes sin cambiar sus aserciones; se agregan tests nuevos de guarda.
- **API**: sin cambios (`POST /api/turnos` idéntico). **DB**: sin migración. **Dependencias**: ninguna nueva.
- **Roadmap**: C-05 y C-07 pasan a depender de C-04b (se actualiza `CHANGES.md` como task del change).
