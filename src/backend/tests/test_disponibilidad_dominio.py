"""Tarea 1.2: cálculo de huecos por franja. Dominio puro, sin DB; reloj y tz inyectados."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.disponibilidad import Franja, Hueco, calcular_huecos, es_inicio_valido

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
LUNES = date(2030, 1, 7)  # lunes, futuro respecto de AHORA
AHORA = datetime(2030, 1, 1, 8, 0, tzinfo=TZ)
MANANA = Franja(0, time(9, 0), time(13, 0))
TARDE = Franja(0, time(15, 0), time(19, 0))


def _dt(h: int, m: int = 0, dia: date = LUNES) -> datetime:
    return datetime(dia.year, dia.month, dia.day, h, m, tzinfo=TZ)


def _inicios(huecos: list[Hueco]) -> list[time]:
    return [h.inicio.timetz().replace(tzinfo=None) for h in huecos]


def _calc(franjas, *, dias=(LUNES,), paso=30, dur=30, ocupados=(), ahora=AHORA):
    return calcular_huecos(list(dias), franjas, paso, dur, list(ocupados), ahora, TZ)


def test_franja_9_a_18_genera_18_huecos_de_30():
    huecos = _calc([Franja(0, time(9, 0), time(18, 0))])
    assert len(huecos) == 18
    assert huecos[0] == Hueco(_dt(9, 0), _dt(9, 30))
    assert huecos[-1] == Hueco(_dt(17, 30), _dt(18, 0))


def test_dos_franjas_mismo_dia_sin_huecos_entre_13_y_15():
    inicios = _inicios(_calc([MANANA, TARDE]))
    assert inicios[0] == time(9, 0) and time(12, 30) in inicios
    assert time(13, 0) not in inicios and time(14, 30) not in inicios
    assert time(15, 0) in inicios and inicios[-1] == time(18, 30)
    assert len(inicios) == 16


def test_tratamiento_60_min_ultimo_de_la_manana_es_12_00():
    inicios = _inicios(_calc([MANANA, TARDE], dur=60))
    assert time(12, 0) in inicios and time(12, 30) not in inicios
    assert time(18, 0) in inicios and time(18, 30) not in inicios


def test_hueco_no_cruza_franjas_contiguas():
    franjas = [Franja(0, time(9, 0), time(13, 0)), Franja(0, time(13, 0), time(17, 0))]
    inicios = _inicios(_calc(franjas, dur=60))
    assert time(12, 30) not in inicios  # cruzaría 13:00
    assert time(12, 0) in inicios and time(13, 0) in inicios


def test_paso_20_sin_tratamiento():
    huecos = _calc([Franja(0, time(9, 0), time(10, 0))], paso=20, dur=20)
    assert _inicios(huecos) == [time(9, 0), time(9, 20), time(9, 40)]
    assert all(h.fin - h.inicio == timedelta(minutes=20) for h in huecos)


def test_dia_sin_franja_es_vacio():
    assert _calc([Franja(1, time(9, 0), time(13, 0))]) == []  # solo martes


def test_sin_franjas_es_vacio():
    assert _calc([]) == []


def test_huecos_pasados_o_en_ahora_excluidos():
    ahora = _dt(10, 0)
    inicios = _inicios(_calc([MANANA], ahora=ahora))
    assert time(10, 0) not in inicios and time(9, 30) not in inicios
    assert inicios[0] == time(10, 30)


def test_ocupado_excluye_solo_su_hueco():
    inicios = _inicios(_calc([MANANA], ocupados=[(_dt(10, 0), _dt(10, 30))]))
    assert time(10, 0) not in inicios
    assert time(9, 30) in inicios and time(10, 30) in inicios


def test_ocupado_10_30_con_duracion_60_excluye_10_00_y_10_30():
    # El spec dice "09:30, 10:00 y 10:30", pero 09:30-10:30 es contiguo (no solapa) a
    # 10:30-11:00 bajo [): se aplica la semántica [) explícita en la misma tarea 1.2.
    inicios = _inicios(_calc([MANANA], dur=60, ocupados=[(_dt(10, 30), _dt(11, 0))]))
    for h in (time(10, 0), time(10, 30)):
        assert h not in inicios
    assert time(9, 0) in inicios and time(9, 30) in inicios and time(11, 0) in inicios


def test_ocupados_contiguos_no_excluyen_vecinos():
    ocupado = (_dt(10, 0), _dt(10, 30))
    inicios = _inicios(_calc([MANANA], ocupados=[ocupado]))
    assert time(9, 30) in inicios and time(10, 30) in inicios


def test_rango_multi_dia_usa_weekday_y_offset_clinica():
    martes = LUNES + timedelta(days=1)
    franjas = [Franja(0, time(9, 0), time(10, 0)), Franja(1, time(14, 0), time(15, 0))]
    huecos = _calc(franjas, dias=[LUNES, martes])
    assert [h.inicio for h in huecos] == [
        _dt(9, 0),
        _dt(9, 30),
        _dt(14, 0, martes),
        _dt(14, 30, martes),
    ]
    assert all(h.inicio.utcoffset() == timedelta(hours=-3) for h in huecos)


def test_es_inicio_valido_grilla_franja_y_futuro():
    franjas = [MANANA, TARDE]
    assert es_inicio_valido(_dt(9, 30), franjas, 30, 30, AHORA, TZ)
    assert not es_inicio_valido(_dt(9, 15), franjas, 30, 30, AHORA, TZ)  # fuera de grilla
    assert not es_inicio_valido(_dt(13, 0), franjas, 30, 30, AHORA, TZ)  # entre franjas
    assert not es_inicio_valido(_dt(12, 30), franjas, 30, 60, AHORA, TZ)  # cruza fin de franja
    assert not es_inicio_valido(_dt(9, 30), franjas, 30, 30, _dt(10, 0), TZ)  # pasado
    assert not es_inicio_valido(_dt(9, 30), [], 30, 30, AHORA, TZ)  # sin franjas
