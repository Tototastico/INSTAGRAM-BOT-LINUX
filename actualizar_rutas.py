import os
import sqlite3
from pathlib import Path
from webapp.db import profile_path

db_path = Path("data/bot.sqlite3")
destino = Path(os.environ["INSTAGRAM_ACCOUNTS_DIR"])

if not destino.is_dir():
    raise SystemExit("No existe la carpeta de destino.")

con = sqlite3.connect(db_path)
con.row_factory = sqlite3.Row

try:
    cuentas = con.execute(
        "SELECT id, name, profile_arg FROM accounts"
    ).fetchall()

    cambios = []

    for cuenta in cuentas:
        nombre = Path(
            cuenta["profile_arg"].replace("\\", "/")
        ).name

        ruta = Path(profile_path(nombre))

        if not ruta.is_dir():
            raise RuntimeError(
                f"Falta el perfil {nombre}: {ruta}"
            )

        cambios.append((nombre, str(ruta), cuenta["id"]))

    # Verificar colisiones antes de actualizar
    rutas = [c[1] for c in cambios]
    if len(set(rutas)) != len(rutas):
        raise RuntimeError("Hay perfiles con rutas duplicadas.")

    respaldo = db_path.with_name("bot.sqlite3.bak")
    with sqlite3.connect(respaldo) as backup:
        con.backup(backup)

    with con:
        con.executemany(
            """UPDATE accounts
               SET profile_arg=?, profile_path=?
               WHERE id=?""",
            cambios
        )

    print("Rutas actualizadas:", len(cambios))
    print("Respaldo:", respaldo)

finally:
    con.close()
