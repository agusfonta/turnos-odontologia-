"""Seguridad mínima (C-02): solo hash para el seed.

`verify`/login/RBAC llegan en C-03, que reutiliza este módulo (sin segunda lib).
"""

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
