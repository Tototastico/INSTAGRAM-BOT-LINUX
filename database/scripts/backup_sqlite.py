#!/usr/bin/env python3
"""
backup_sqlite.py - Respaldo seguro y consistente de SQLite (WAL compatible).
Usa la SQLite Online Backup API para garantizar consistencia atómica sin bloquear lectores.
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def backup_database(source_path: Path, output_dir: Path | None = None) -> Path:
    if not source_path.is_file():
        raise FileNotFoundError(f"El archivo origen de base de datos no existe: {source_path}")

    target_dir = output_dir or (source_path.parent / "backups")
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = target_dir / f"{source_path.stem}_{timestamp}.sqlite3"

    # Conectar origen con timeout y WAL compatible
    source_con = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
    try:
        # Verificar integridad básica antes de respaldar
        cur = source_con.cursor()
        integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity.lower() != "ok":
            raise RuntimeError(f"Integridad previa fallida en la base origen: {integrity}")

        dest_con = sqlite3.connect(backup_file)
        try:
            with dest_con:
                source_con.backup(dest_con, pages=250, sleep=0.01)
        finally:
            dest_con.close()
    finally:
        source_con.close()

    # Validar la copia generada
    verify_con = sqlite3.connect(backup_file)
    try:
        integrity = verify_con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity.lower() != "ok":
            backup_file.unlink(missing_ok=True)
            raise RuntimeError(f"El archivo de backup generado está corrupto: {integrity}")
    finally:
        verify_con.close()

    return backup_file


def main():
    parser = argparse.ArgumentParser(description="Respaldo seguro de base SQLite")
    parser.add_argument("--db", type=str, default=os.environ.get("INSTAGRAM_BOT_DB_PATH", "data/bot.sqlite3"),
                        help="Ruta de la base de datos origen")
    parser.add_argument("--out", type=str, default=None,
                        help="Directorio de destino para el respaldo")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    out_dir = Path(args.out).resolve() if args.out else None

    try:
        backup_path = backup_database(db_path, out_dir)
        print(f"[OK] Respaldo exitoso creado en: {backup_path}")
        print(f"Tamaño: {backup_path.stat().st_size} bytes")
    except Exception as exc:
        print(f"[ERROR] Error al respaldar la base de datos: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
