"""C-04b D6: los casos de uso y los routers no cierran transacciones (solo la UoW)."""

import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
CARPETAS = ("app/application", "app/api")
METODOS_PROHIBIDOS = {"commit", "rollback"}


def _hallazgos(fuente: str, nombre: str) -> list[str]:
    """`archivo:linea` de cada llamada `X.commit()` / `X.rollback()` (AST: ignora strings y comentarios)."""
    arbol = ast.parse(fuente)
    return [
        f"{nombre}:{nodo.lineno}"
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and nodo.func.attr in METODOS_PROHIBIDOS
    ]


def test_detector_ignora_comentarios_y_docstrings():
    fuente = '"""Nunca session.commit() aqui."""\n# session.rollback()\nx = "session.commit()"\n'
    assert _hallazgos(fuente, "sintetico.py") == []


def test_detector_encuentra_llamada_real():
    fuente = "def f(s):\n    s.rollback()\n"
    assert _hallazgos(fuente, "sintetico.py") == ["sintetico.py:2"]


def test_application_y_api_no_llaman_commit_ni_rollback():
    hallazgos: list[str] = []
    for carpeta in CARPETAS:
        for archivo in sorted((BACKEND_DIR / carpeta).rglob("*.py")):
            rel = archivo.relative_to(BACKEND_DIR).as_posix()
            hallazgos += _hallazgos(archivo.read_text(encoding="utf-8"), rel)
    assert not hallazgos, f"commit/rollback fuera de la UoW: {hallazgos}"
