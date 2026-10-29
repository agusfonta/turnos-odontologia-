---
name: turno-use-case
description: Receta para todo caso de uso que muta un turno existente o lo crea a mano - alta manual, reprogramar, cancelar, confirmar - con dos puertas finas (secretaria JWT en C-05, paciente por token publico en C-07) al MISMO caso de uso. Usar al proponer o implementar C-05/C-07 o cualquier endpoint de cambio de turno. Se apoya en uow-transacciones.
---

# turno-use-case

Construye sobre `uow-transacciones` (leerla; no se duplica aca: UoW, DTO, efectos post-commit, 23P01). Referencia viva: `app/application/reservas.py` y `app/api/turnos.py`. Esta skill NO reescribe reglas de negocio: viven en `knowledge-base/05_reglas_de_negocio.md` y `openspec/specs/turnos/spec.md`.

> Gobernanza: C-05/C-07 son MEDIO (implementar con checkpoints). Cambiar el contrato de `reservar_turno` (firma, DTO, flujo de conflicto) es CRITICO: aprobacion humana previa.

## Layout

- Una funcion por operacion en `app/application/`: `alta_manual_turno`, `reprogramar_turno`, `cancelar_turno`, `confirmar_turno` (nombres sugeridos; firma al estilo `reservar_turno(uow_factory, ..., ahora, tz)`).
- Routers finos: autenticar/resolver actor -> llamar el caso de uso -> efectos post-commit -> mapear DTO a `response_model`. Sin logica de negocio en el router.
- Dos puertas, un caso de uso. La puerta secretaria (JWT; `get_optional_staff` en `app/api/deps.py` es opcional, para staff obligatorio usar `require_role`) y la puerta token (publica) pasan al caso de uso un actor explicito: `AuditoriaActor.SECRETARIA` + `actor_user_id`, o `AuditoriaActor.PACIENTE` sin user. La puerta token localiza el turno por `Turno.token_publico` dentro del caso de uso; token invalido da el MISMO 404 (misma clase y mensaje) que turno inexistente, sin datos del turno.

## Receta dentro de UN `with uow_factory() as session:`

1. Cargar el turno (404 si no existe / token invalido).
2. Validar la transicion con `app/domain/turno_estados.py` (`transicionar(actual, nuevo)`; lanza `TransicionInvalidaError`). No inventar otra maquina de estados.
3. Anticipacion con `get_settings().CANCEL_MIN_HOURS` (nunca hardcode) para reprogramar/cancelar. Quien esta sujeto: ver "Ambiguedades".
4. Reprogramar: revalidar el nuevo hueco con `es_inicio_valido(...)` + `hay_ocupacion(...)` EXCLUYENDO el propio turno (hoy no hay parametro de exclusion, ver "Ambiguedades").
5. Aplicar el cambio con timestamptz (RN-GL-02): `inicio`/`fin` aware; convertir a `ZoneInfo(CLINIC_TIMEZONE)` solo al responder.
6. Escribir `AuditoriaTurno(turno_id, accion, actor_tipo, actor_user_id, detalle)` en el mismo `with` (RN-GL-01). Es append-only: un fallo posterior la deshace por rollback.
7. `flush()` final y DTO plano.

DESPUES del `with` (router/orquestador): tocar los jobs de recordatorio en Redis. Hoy `RecordatorioQueue` solo tiene `encolar` (ZADD idempotente, score `inicio - 24h`): re-encolar con el nuevo `inicio` sirve para reprogramar; NO existe cancelar/desencolar (ZREM). C-05/C-07 deben agregarlo con tests (reintento, nunca lanza, no se llama sin commit) en vez de inventar comportamiento.

### Variante `confirmar`

Sin anticipacion y sin revalidar hueco: solo `transicionar(RESERVADO, CONFIRMADO)` + auditoria (RN-NO-02: confirmacion 1-clic sin login). Idempotencia ante doble clic: decidir en el propose.

## Matriz de actores

Fuente: `knowledge-base/03_actores_y_roles.md` (RBAC y rutas publicas), RN-AG-04, RN-TU-03. Resumen operativo, sin copiar el texto de las reglas:
- Alta manual y sobreturno (columna `Turno.sobreturno`, marca explicita): solo secretaria autenticada. La puerta token no puede crear.
- Reprogramar/cancelar: secretaria (cualquier turno) y paciente por token (el suyo).
- Confirmar: paciente por token (RN-NO-02) y staff segun la matriz RBAC.

## Mapeo de errores (un solo lugar)

Clases de `app/core/exceptions.py` (handler `AppError` -> `{detail, code, ...extra}`):
- Solape (chequeo o 23P01): `HuecoOcupadoError(huecos)` -> 409, huecos leidos en UoW nueva (`_conflicto`).
- Inicio invalido: `InicioInvalidoError` -> 422.
- Inexistente / token invalido: subclase de `NotFoundError` -> 404 identico en ambos casos.
- Anticipacion insuficiente y transicion invalida: HOY NO HAY clase `AppError` (solo `TransicionInvalidaError(ValueError)` en dominio). Crear subclases 422 (p.ej. `AnticipacionInsuficienteError`, `TransicionNoPermitidaError`) y convertir `TransicionInvalidaError` dentro del caso de uso.
- `IntegrityError` con sqlstate distinto de 23P01 -> se re-lanza (500).

## Tests minimos por operacion

- Camino feliz y cada error (404, 409 con huecos, 422 anticipacion/transicion/inicio).
- Auditoria escrita en exito y NO escrita en fallo, leida desde otra sesion (`AuditoriaTurno` es append-only: el aislamiento es la DB clonada por test).
- Ambas puertas (secretaria y token) llegan al mismo caso de uso (espia/monkeypatch sobre la funcion de `app.application.*`) y producen la misma auditoria salvo `actor_tipo`.
- Concurrencia con `threading.Barrier` si toca agenda (reprogramar/alta manual), como `tests/test_turnos_concurrencia.py`.
- Orden commit -> efecto Redis; fallo de Redis no falla el request; fallo de COMMIT no encola.
- Helpers: `factoria_espia`/`UowEspia` en `tests/support.py`; fixtures `entorno_api`/`mig_session` en `tests/conftest.py`. En los 404 por token verificar que el cuerpo no filtra datos del turno.

## Ambiguedades a resolver en el propose de C-05/C-07

- TODO RN-TU-01 dice "no se puede cancelar/reprogramar con menos de la anticipacion minima" sin distinguir actor; CHANGES.md C-05 la aplica tambien a la secretaria (DELETE/PATCH) y 03_actores la menciona para el token. Confirmar si la secretaria esta sujeta o exenta; mientras no se decida, aplicar a ambas puertas y parametrizar por actor.
- TODO `hay_ocupacion`/`TurnoRepository.ocupados_en_rango` no excluyen un turno por id: reprogramar a un hueco que solape con el propio turno daria un falso 409. Agregar parametro de exclusion (repositorio, con tests).
- TODO Sobreturno: hoy solo existe la columna `Turno.sobreturno` (la constraint exime a esos turnos, ver spec). Definir en C-05 el campo de entrada y como se saltea `hay_ocupacion` solo con marca + secretaria.
- TODO Falta `RecordatorioQueue` cancelar (ZREM); reprogramar = re-`encolar`.
- TODO Sin clases `AppError` para anticipacion/transicion/turno-no-encontrado. Rutas por token: CHANGES.md C-07 usa `/api/turnos/por-token/{token}`, 03_actores lista `/turnos/{token}/confirmar|cancelar` (rutas de SPA/WhatsApp); alinear.
- TODO Reprogramar un turno `confirmado`: definir si vuelve a `reservado` (RN-TU-04 no tiene esa transicion) o conserva el estado.

## Esta skill NO

Repite reglas de negocio ni texto de la KB/specs: se cita `knowledge-base/` y `openspec/specs/turnos/spec.md` y se lee antes de implementar.
