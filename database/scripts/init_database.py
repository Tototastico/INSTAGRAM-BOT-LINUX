#!/usr/bin/env python3
"""
init_database.py - Inicialización limpia del esquema de base de datos desde schema.sql.
Permite arrancar una instancia nueva en Linux VPS sin arrastrar datos legacy.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path


def init_database(db_path: Path, schema_file: Path | None = None) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = schema_file or (Path(__file__).resolve().parents[1] / "schema.sql")

    if not schema_path.is_file():
        raise FileNotFoundError(f"Archivo de esquema no encontrado: {schema_path}")

    sql = schema_path.read_text(encoding="utf-8")

    con = sqlite3.connect(db_path, timeout=30)
    try:
        with con:
            con.executescript(sql)
        print(f"[OK] Base de datos inicializada exitosamente en: {db_path}")
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description="Inicialización de base de datos SQLite")
    parser.add_argument("--db", type=str, default=os.environ.get("INSTAGRAM_BOT_DB_PATH", "data/bot.sqlite3"),
                        help="Ruta de la base de datos a inicializar")
    parser.add_argument("--schema", type=str, default=None,
                        help="Ruta del archivo schema.sql")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    schema_path = Path(args.schema).resolve() if args.schema else None

    try:
        init_database(db_path, schema_path)
    except Exception as exc:
        print(f"[ERROR] Error al inicializar la base de datos: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
