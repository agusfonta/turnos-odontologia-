"""Cálculo de huecos de agenda. Dominio puro: reloj y zona horaria inyectados, sin I/O.

Las franjas son horas locales de la clínica (TIME sin zona); el instante se arma
con `zoneinfo` sobre la fecha local para que un cambio de offset no corra la grilla.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Franja:
    dia_semana: int  # 0 = lunes (date.weekday())
    hora_inicio: time
    hora_fin: time


@dataclass(frozen=True)
class Hueco:
    inicio: datetime
    fin: datetime


Ocupado = tuple[datetime, datetime]


def _local(fecha: date, hora: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(fecha, hora, tzinfo=tz)


def _inicios_de_franja(
    fecha: date, franja: Franja, paso_min: int, duracion_min: int, tz: ZoneInfo
) -> Iterable[datetime]:
    paso = timedelta(minutes=paso_min)
    duracion = timedelta(minutes=duracion_min)
    fin_franja = _local(fecha, franja.hora_fin, tz)
    inicio = _local(fecha, franja.hora_inicio, tz)
    while inicio + duracion <= fin_franja:
        yield inicio
        inicio += paso


def _solapa(a_ini: datetime, a_fin: datetime, b_ini: datetime, b_fin: datetime) -> bool:
    return a_ini < b_fin and b_ini < a_fin  # intervalos [) semiabiertos


def calcular_huecos(
    dias: Sequence[date],
    franjas: Sequence[Franja],
    paso_min: int,
    duracion_min: int,
    ocupados: Sequence[Ocupado],
    ahora: datetime,
    tz: ZoneInfo,
) -> list[Hueco]:
    duracion = timedelta(minutes=duracion_min)
    huecos: list[Hueco] = []
    for dia in dias:
        for franja in sorted(
            (f for f in franjas if f.dia_semana == dia.weekday()), key=lambda f: f.hora_inicio
        ):
            for inicio in _inicios_de_franja(dia, franja, paso_min, duracion_min, tz):
                fin = inicio + duracion
                if inicio <= ahora:
                    continue
                if any(_solapa(inicio, fin, o_ini, o_fin) for o_ini, o_fin in ocupados):
                    continue
                huecos.append(Hueco(inicio, fin))
    return huecos


def es_inicio_valido(
    inicio: datetime,
    franjas: Sequence[Franja],
    paso_min: int,
    duracion_min: int,
    ahora: datetime,
    tz: ZoneInfo,
) -> bool:
    """Grilla de alguna franja + cabe en esa franja + futuro (ignora ocupación)."""
    if inicio <= ahora:
        return False
    inicio_local = inicio.astimezone(tz)
    dia = inicio_local.date()
    return any(
        inicio_local == candidato
        for franja in franjas
        if franja.dia_semana == dia.weekday()
        for candidato in _inicios_de_franja(dia, franja, paso_min, duracion_min, tz)
    )
