"""Conexión a la base del portal.

Base propia (`portal`), separada de `conciliador`: nada de acá toca los 2822
movimientos ni los 78 comprobantes que usa `web/`.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

URL = os.environ.get(
    "PORTAL_DATABASE_URL",
    "postgresql+psycopg://luisparmigiani@localhost:5432/portal",
)

motor = create_engine(URL)
Sesion = sessionmaker(motor)
