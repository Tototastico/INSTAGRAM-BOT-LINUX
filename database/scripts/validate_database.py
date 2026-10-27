#!/usr/bin/env python3
"""
validate_database.py - Validación exhaustiva de integridad y esquema de SQLite.
Ejecuta:
  - PRAGMA integrity_check
  - PRAGMA quick_check
  - PRAGMA foreign_key_check
  - Inspección de tablas y columnas requeridas
  - Detección de rutas Windows obsoletas en accounts
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

REQUIRED_TABLES = {"meta", "accounts", "draws", "assignments", "tasks", "events"}


def validate_database(db_path: Path) -> dict:
    if not db_path.is_file():
        raise FileNotFoundError(f"No existe el archivo de base de datos: {db_path}")

    report = {
        "path": str(db_path),
        "size_bytes": db_path.stat().st_size,
        "integrity_check": "FAILED",
        "quick_check": "FAILED",
        "fk_violations": [],
        "missing_tables": [],
        "windows_paths_count": 0,
        "accounts_count": 0,
        "tasks_count": 0,
        "valid": False,
    }

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()

        # 1. PRAGMA integrity_check
        res = cur.execute("PRAGMA integrity_check").fetchall()
        if len(res) == 1 and res[0][0].lower() == "ok":
            report["integrity_check"] = "OK"
        else:
            report["integrity_check"] = [r[0] for r in res]

        # 2. PRAGMA quick_check
        res = cur.execute("PRAGMA quick_check").fetchall()
        if len(res) == 1 and res[0][0].lower() == "ok":
            report["quick_check"] = "OK"
        else:
            report["quick_check"] = [r[0] for r in res]

        # 3. PRAGMA foreign_key_check
        fk_errors = cur.execute("PRAGMA foreign_key_check").fetchall()
        report["fk_violations"] = [dict(r) for r in fk_errors]

        # 4. Verificación de tablas existentes
        existing_tables = {
            r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        report["missing_tables"] = list(REQUIRED_TABLES - existing_tables)

        if "accounts" in existing_tables:
            accounts = cur.execute("SELECT id, profile_arg, profile_path FROM accounts").fetchall()
            report["accounts_count"] = len(accounts)
            for acc in accounts:
                path_str = acc["profile_path"] or ""
                # Si contiene contrabarra o letras de unidad de Windows tipo C: o E:
                if "\\" in path_str or (len(path_str) > 1 and path_str[1] == ":"):
                    report["windows_paths_count"] += 1

        if "tasks" in existing_tables:
            report["tasks_count"] = cur.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

        report["valid"] = (
            report["integrity_check"] == "OK"
            and report["quick_check"] == "OK"
            and len(report["fk_violations"]) == 0
            and len(report["missing_tables"]) == 0
        )
    finally:
        con.close()

    return report


def main():
    parser = argparse.ArgumentParser(description="Validación de integridad y esquema de SQLite")
    parser.add_argument("--db", type=str, default=os.environ.get("INSTAGRAM_BOT_DB_PATH", "data/bot.sqlite3"),
                        help="Ruta de la base de datos a validar")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    try:
        rep = validate_database(db_path)
        print("=== REPORTE DE VALIDACIÓN SQLITE ===")
        print(f"Ruta: {rep['path']}")
        print(f"Tamaño: {rep['size_bytes']} bytes")
        print(f"Integrity check: {rep['integrity_check']}")
        print(f"Quick check:     {rep['quick_check']}")
        print(f"Violaciones FK:  {len(rep['fk_violations'])}")
        print(f"Tablas faltantes:{rep['missing_tables']}")
        print(f"Cuentas totales: {rep['accounts_count']}")
        print(f"Rutas Windows:   {rep['windows_paths_count']}")
        print(f"Tareas totales:  {rep['tasks_count']}")
        print(f"Resultado final: {'[VALIDA]' if rep['valid'] else '[INVALIDA]'}")

        if not rep["valid"]:
            sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] Error durante la validación: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
