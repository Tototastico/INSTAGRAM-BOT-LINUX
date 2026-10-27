#!/usr/bin/env python3
"""
migrate_paths.py - Migración transaccional de rutas de cuentas en SQLite.
Convierte las rutas en `accounts.profile_path` desde el formato Windows
hacia la ruta canónica configurada para Linux (o la ruta canónica de la plataforma destino).

Características:
  - Soporta modo preview / dry-run sin modificar datos.
  - Comprueba colisiones de perfiles y nombres duplicados.
  - Si no es dry-run, crea un respaldo verificado previo con SQLite Online Backup.
  - Ejecuta la actualización dentro de una transacción atómica.
  - Verifica la integridad posterior con PRAGMA integrity_check.
  - Es idempotente: puede ejecutarse múltiples veces sin alterar datos ni romper rutas ya migradas.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Agregar raíz para importar webapp.paths
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from webapp.paths import resolve_profile_path, get_accounts_dir
from backup_sqlite import backup_database
from validate_database import validate_database


def migrate_account_paths(db_path: Path, target_accounts_dir: Path, apply: bool = False, check_dirs: bool = False) -> dict:
    if not db_path.is_file():
        raise FileNotFoundError(f"La base de datos no existe: {db_path}")

    # Validar integridad previa
    pre_val = validate_database(db_path)
    if not pre_val["valid"]:
        raise RuntimeError(f"La base de datos no es válida antes de migrar: {pre_val}")

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT id, name, profile_arg, profile_path FROM accounts").fetchall()

        plan = []
        new_paths_seen = {}
        missing_dirs = []

        for r in rows:
            acc_id = r["id"]
            name = r["name"]
            profile_arg = r["profile_arg"]
            current_path = r["profile_path"]

            # Calcular la nueva ruta canónica
            # Si profile_arg es 'cuenta1' o 'accounts/cuenta1', resolve_profile_path lo normaliza
            target_path = resolve_profile_path(profile_arg, accounts_dir=target_accounts_dir)

            # Chequear colisiones
            if target_path in new_paths_seen:
                prev_id, prev_name = new_paths_seen[target_path]
                raise RuntimeError(
                    f"Colisión de rutas detectada: Cuenta #{acc_id} ('{name}') y #{prev_id} ('{prev_name}') "
                    f"producen la misma ruta: {target_path}"
                )
            new_paths_seen[target_path] = (acc_id, name)

            # Verificar si existe la carpeta en disco si check_dirs está activo
            if check_dirs and not Path(target_path).is_dir():
                missing_dirs.append((acc_id, name, target_path))

            needs_update = (current_path != target_path)
            plan.append({
                "id": acc_id,
                "name": name,
                "profile_arg": profile_arg,
                "old_path": current_path,
                "new_path": target_path,
                "changed": needs_update
            })

        if missing_dirs:
            print(f"[AVISO] {len(missing_dirs)} carpetas de perfiles no existen actualmente en disco:")
            for m in missing_dirs:
                print(f"  - Cuenta #{m[0]} ({m[1]}): {m[2]}")

        changes_to_apply = [item for item in plan if item["changed"]]

        if not apply:
            return {
                "applied": False,
                "total_accounts": len(rows),
                "accounts_to_update": len(changes_to_apply),
                "plan": plan
            }

        # Aplicar cambios
        if not changes_to_apply:
            print("[INFO] Todas las rutas ya están actualizadas. No se requieren cambios (idempotente).")
            return {
                "applied": True,
                "total_accounts": len(rows),
                "accounts_to_update": 0,
                "plan": plan
            }

        # 1. Crear respaldo previo
        print("[*] Creando respaldo previo antes de aplicar la migración...")
        backup_file = backup_database(db_path)
        print(f"[OK] Respaldo generado en: {backup_file}")

        # 2. Ejecutar transacción
        with con:
            for item in changes_to_apply:
                con.execute(
                    "UPDATE accounts SET profile_path = ? WHERE id = ?",
                    (item["new_path"], item["id"])
                )

        # 3. Validar integridad post-migración
        cur = con.cursor()
        integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity.lower() != "ok":
            raise RuntimeError(f"Error de integridad post-migración: {integrity}")

        return {
            "applied": True,
            "total_accounts": len(rows),
            "accounts_to_update": len(changes_to_apply),
            "backup_file": str(backup_file),
            "plan": plan
        }

    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description="Migración de rutas de perfiles en SQLite")
    parser.add_argument("--db", type=str, default=os.environ.get("INSTAGRAM_BOT_DB_PATH", "data/bot.sqlite3"),
                        help="Ruta de la base de datos")
    parser.add_argument("--accounts-dir", type=str,
                        default=os.environ.get("INSTAGRAM_ACCOUNTS_DIR", "accounts"),
                        help="Directorio base de perfiles de cuentas")
    parser.add_argument("--apply", action="store_true", help="Aplicar cambios (sin este flag solo hace preview)")
    parser.add_argument("--check-dirs", action="store_true", help="Verificar que las carpetas existan en el sistema de archivos")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    target_accounts_dir = Path(args.accounts_dir).resolve()

    print(f"=== MIGRACIÓN DE RUTAS DE CUENTAS SQLITE ===")
    print(f"Base de datos:  {db_path}")
    print(f"Directorio cuentas: {target_accounts_dir}")
    print(f"Modo:           {'APLICAR CAMBIOS' if args.apply else 'PREVIEW (DRY-RUN)'}")
    print("-" * 50)

    try:
        res = migrate_account_paths(db_path, target_accounts_dir, apply=args.apply, check_dirs=args.check_dirs)
        print(f"Total cuentas analizadas: {res['total_accounts']}")
        print(f"Cuentas a actualizar:     {res['accounts_to_update']}")
        print("-" * 50)
        for p in res["plan"]:
            status = "ACTUALIZAR" if p["changed"] else "SIN CAMBIO"
            print(f"[{status}] #{p['id']} ({p['name']})")
            print(f"   Anterior: {p['old_path']}")
            print(f"   Nuevo:    {p['new_path']}")

        if not args.apply and res["accounts_to_update"] > 0:
            print("\nPara aplicar los cambios definitivamente, vuelve a ejecutar agregando el flag: --apply")
        elif args.apply:
            print(f"\n[OK] Migración aplicada con éxito. Respaldo: {res.get('backup_file')}")

    except Exception as exc:
        print(f"\n[ERROR] Falló la migración: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
