"""Jerarquía AppError + handlers globales (respuesta problem+json consistente)."""

from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.agenda import TurnoEnConflicto


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, detail: str = "Internal server error") -> None:
        super().__init__(detail)
        self.detail = detail

    def extra(self) -> dict[str, object]:
        """Campos adicionales tipados que se suman a `{detail, code}`."""
        return {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ProfesionalNoEncontradoError(NotFoundError):
    code = "profesional_no_encontrado"

    def __init__(self, detail: str = "Profesional no encontrado") -> None:
        super().__init__(detail)


class TratamientoNoEncontradoError(NotFoundError):
    code = "tratamiento_no_encontrado"

    def __init__(self, detail: str = "Tratamiento no encontrado") -> None:
        super().__init__(detail)


class TurnoNoEncontradoError(NotFoundError):
    code = "turno_no_encontrado"

    def __init__(self, detail: str = "Turno no encontrado") -> None:
        super().__init__(detail)


class RangoInvalidoError(AppError):
    status_code = 422
    code = "rango_invalido"


class InicioInvalidoError(AppError):
    """`inicio` fuera de grilla/franja/futuro (RN-TU-02)."""

    status_code = 422
    code = "inicio_invalido"

    def __init__(self, detail: str = "El inicio no es un hueco de agenda válido") -> None:
        super().__init__(detail)


class HuecoOcupadoError(AppError):
    """409 con la lista actualizada de huecos del mismo profesional y día."""

    status_code = 409
    code = "hueco_ocupado"

    def __init__(self, huecos: list[dict[str, str]], detail: str = "El hueco ya está ocupado") -> None:
        super().__init__(detail)
        self.huecos = huecos

    def extra(self) -> dict[str, object]:
        return {"huecos": self.huecos}


class TransicionNoPermitidaError(AppError):
    """422: el estado actual del turno no admite la operacion (D8)."""

    status_code = 422
    code = "transicion_no_permitida"

    def __init__(
        self, estado_actual: str, detail: str = "La transición de estado no está permitida"
    ) -> None:
        super().__init__(detail)
        self.estado_actual = estado_actual

    def extra(self) -> dict[str, object]:
        return {"estado_actual": self.estado_actual}


class AnticipacionInsuficienteError(AppError):
    """422: el turno cae dentro de la ventana de anticipacion minima (D7/D8)."""

    status_code = 422
    code = "anticipacion_insuficiente"

    def __init__(
        self, min_horas: int, detail: str = "No se cumple la anticipación mínima"
    ) -> None:
        super().__init__(detail)
        self.min_horas = min_horas

    def extra(self) -> dict[str, object]:
        return {"min_horas": self.min_horas}


class BloqueoNoEncontradoError(NotFoundError):
    code = "bloqueo_no_encontrado"

    def __init__(self, detail: str = "Bloqueo no encontrado") -> None:
        super().__init__(detail)


class BloqueoConTurnosError(AppError):
    """409: el rango del bloqueo pisa turnos `reservado`/`confirmado` (C-06 D1/D7)."""

    status_code = 409
    code = "bloqueo_con_turnos"

    def __init__(
        self,
        turnos: Sequence[TurnoEnConflicto],
        detail: str = "El rango del bloqueo tiene turnos activos",
    ) -> None:
        super().__init__(detail)
        self.turnos = list(turnos)

    def extra(self) -> dict[str, object]:
        return {
            "turnos": [
                {
                    "id": str(t.id),
                    "inicio": t.inicio.isoformat(),
                    "fin": t.fin.isoformat(),
                    "estado": t.estado.value,
                }
                for t in self.turnos
            ]
        }


class SinProfesionalAsociadoError(AppError):
    """403: el odontologo no tiene profesional vinculado (`profesionales.user_id`)."""

    status_code = 403
    code = "sin_profesional_asociado"

    def __init__(self, detail: str = "El usuario no tiene un profesional asociado") -> None:
        super().__init__(detail)


class AgendaAjenaError(AppError):
    """403: un odontologo pidio la agenda de otro profesional (sin consultar si existe)."""

    status_code = 403
    code = "agenda_ajena"

    def __init__(self, detail: str = "No puede consultar la agenda de otro profesional") -> None:
        super().__init__(detail)


class ProfesionalRequeridoError(AppError):
    """422: la secretaria debe indicar `profesional_id` (no hay profesional por defecto)."""

    status_code = 422
    code = "profesional_requerido"

    def __init__(self, detail: str = "Debe indicar el profesional") -> None:
        super().__init__(detail)


def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, **exc.extra()},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
