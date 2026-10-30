"""C-06 3.1: rango de agenda (dominio puro, sin DB)."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.agenda import limites_instantes, rango_agenda

BA = ZoneInfo("America/Argentina/Buenos_Aires")


def test_semana_de_un_miercoles():
    assert rango_agenda(date(2030, 3, 6), "semana") == (date(2030, 3, 4), date(2030, 3, 10))


def test_vista_dia_devuelve_el_mismo_dia():
    assert rango_agenda(date(2030, 3, 6), "dia") == (date(2030, 3, 6), date(2030, 3, 6))


def test_semana_de_un_lunes_es_esa_misma_semana():
    assert rango_agenda(date(2030, 3, 4), "semana") == (date(2030, 3, 4), date(2030, 3, 10))


def test_semana_de_un_domingo_es_la_del_lunes_anterior():
    assert rango_agenda(date(2030, 3, 10), "semana") == (date(2030, 3, 4), date(2030, 3, 10))


def test_semana_que_cruza_el_anio():
    # 2030-01-01 es martes: la semana empieza el lunes 2029-12-31.
    assert rango_agenda(date(2030, 1, 1), "semana") == (date(2029, 12, 31), date(2030, 1, 6))


def test_vista_invalida_levanta_value_error():
    with pytest.raises(ValueError):
        rango_agenda(date(2030, 3, 6), "mes")  # type: ignore[arg-type]


def test_limites_de_un_dia_en_buenos_aires():
    ini, fin = limites_instantes(date(2030, 3, 6), date(2030, 3, 6), BA)
    assert ini == datetime(2030, 3, 6, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
    assert fin == datetime(2030, 3, 7, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
    assert ini.tzinfo is not None and fin - ini == timedelta(hours=24)


def test_limites_de_una_semana_son_semiabiertos_hasta_el_lunes_siguiente():
    ini, fin = limites_instantes(date(2030, 3, 4), date(2030, 3, 10), BA)
    assert ini == datetime(2030, 3, 4, 3, 0, tzinfo=timezone.utc)
    assert fin == datetime(2030, 3, 11, 3, 0, tzinfo=timezone.utc)  # 00:00 local del lunes


def test_limites_con_dst_siguen_en_medianoche_local():
    """Santiago termina el horario de verano el 1er sabado de abril: los limites de la semana
    tienen offsets distintos pero ambos son 00:00 locales (no +7 dias fijos en UTC)."""
    santiago = ZoneInfo("America/Santiago")
    ini, fin = limites_instantes(date(2030, 4, 1), date(2030, 4, 7), santiago)
    assert (ini.hour, ini.minute) == (0, 0) and (fin.hour, fin.minute) == (0, 0)
    assert ini.utcoffset() != fin.utcoffset()
    assert fin.astimezone(timezone.utc) - ini.astimezone(timezone.utc) == timedelta(days=7, hours=1)
