#!/usr/bin/env python3
"""
restore_sqlite.py - Restauración segura de base de datos desde un archivo de backup.
Pasos:
  1. Valida la integridad del archivo de backup origen.
  2. Crea un respaldo de seguridad del archivo actual antes de sobrescribirlo (si existe).
  3. Restaura mediante sqlite3.backup o copia consistente atómica.
  4. Valida la integridad de la base restaurada.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from validate_database import validate_database


def restore_database(backup_file: Path, target_db: Path) -> None:
    if not backup_file.is_file():
        raise FileNotFoundError(f"El archivo de backup no existe: {backup_file}")

    print(f"[*] Validando integridad del backup origen: {backup_file}...")
    b_val = validate_database(backup_file)
    if not b_val["valid"]:
        raise RuntimeError(f"El archivo de backup origen no es válido: {b_val}")

    target_db.parent.mkdir(parents=True, exist_ok=True)

    # Si ya existe una base destino, hacer backup de seguridad inmediato antes de tocarla
    if target_db.is_file():
        safety_name = f"{target_db.stem}_pre_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.sqlite3.bak"
        safety_path = target_db.parent / safety_name
        print(f"[*] Creando copia de seguridad del estado actual en: {safety_path}...")
        shutil.copy2(target_db, safety_path)
        # Limpiar posibles archivos wal/shm
        wal = target_db.with_name(target_db.name + "-wal")
        shm = target_db.with_name(target_db.name + "-shm")
        if wal.exists():
            wal.unlink()
        if shm.exists():
            shm.unlink()

    print(f"[*] Restaurando hacia: {target_db}...")
    src_con = sqlite3.connect(backup_file)
    dest_con = sqlite3.connect(target_db)
    try:
        with dest_con:
            src_con.backup(dest_con)
    finally:
        dest_con.close()
        src_con.close()

    print("[*] Validando base de datos restaurada...")
    t_val = validate_database(target_db)
    if not t_val["valid"]:
        raise RuntimeError(f"La base restaurada no superó la validación: {t_val}")

    print("[OK] Base de datos restaurada exitosamente y validada.")


def main():
    parser = argparse.ArgumentParser(description="Restauración de SQLite desde un respaldo")
    parser.add_argument("--backup", type=str, required=True, help="Ruta al archivo de backup a restaurar")
    parser.add_argument("--target", type=str, default=os.environ.get("INSTAGRAM_BOT_DB_PATH", "data/bot.sqlite3"),
                        help="Ruta de destino donde restaurar la base")
    args = parser.parse_args()

    backup_file = Path(args.backup).resolve()
    target_db = Path(args.target).resolve()

    try:
        restore_database(backup_file, target_db)
    except Exception as exc:
        print(f"[ERROR] Error al restaurar: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
