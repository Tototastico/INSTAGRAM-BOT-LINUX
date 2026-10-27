import os
import shutil
import sqlite3
import sys
from pathlib import Path
import pytest

from webapp.paths import resolve_profile_path, get_accounts_dir, get_db_path
from webapp.instance_lock import SingleInstanceLock
from database.scripts.init_database import init_database
from database.scripts.backup_sqlite import backup_database
from database.scripts.validate_database import validate_database
from database.scripts.migrate_paths import migrate_account_paths
from database.scripts.restore_sqlite import restore_database


def test_paths_resolution(tmp_path):
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()

    # Resolver nombre simple
    p1 = resolve_profile_path("cuenta1", accounts_dir=accounts_dir)
    assert Path(p1).name.lower() == "cuenta1"

    # Resolver prefijo accounts/
    p2 = resolve_profile_path("accounts/cuenta1", accounts_dir=accounts_dir)
    assert p1 == p2

    # Resolver separadores estilo Windows accounts\cuenta1
    p3 = resolve_profile_path("accounts\\cuenta1", accounts_dir=accounts_dir)
    assert p1 == p3

    # Rutas inválidas deben fallar
    with pytest.raises(ValueError):
        resolve_profile_path("../cuenta_invalida", accounts_dir=accounts_dir)
    with pytest.raises(ValueError):
        resolve_profile_path("", accounts_dir=accounts_dir)


def test_instance_lock(tmp_path):
    lock_file = tmp_path / "test.lock"
    lock1 = SingleInstanceLock(lock_file)
    lock2 = SingleInstanceLock(lock_file)

    assert lock1.acquire() is True
    assert lock1.is_locked is True

    # El segundo intento no debe poder adquirir el bloqueo concurrente
    assert lock2.acquire() is False

    lock1.release()
    assert lock1.is_locked is False

    # Ahora el segundo debe poder adquirirlo
    assert lock2.acquire() is True
    lock2.release()


def test_database_init_backup_and_validate(tmp_path):
    db_file = tmp_path / "test_bot.sqlite3"
    schema_file = Path(__file__).resolve().parents[1] / "database" / "schema.sql"

    # 1. Inicialización
    init_database(db_file, schema_file)
    assert db_file.is_file()

    # 2. Validación
    report = validate_database(db_file)
    assert report["valid"] is True
    assert report["integrity_check"] == "OK"
    assert len(report["missing_tables"]) == 0

    # 3. Respaldo
    backup_file = backup_database(db_file, output_dir=tmp_path / "backups")
    assert backup_file.is_file()
    b_report = validate_database(backup_file)
    assert b_report["valid"] is True


def test_database_migration_idempotent(tmp_path):
    db_file = tmp_path / "migrate_test.sqlite3"
    schema_file = Path(__file__).resolve().parents[1] / "database" / "schema.sql"
    init_database(db_file, schema_file)

    # Insertar cuentas de prueba con ruta estilo Windows
    con = sqlite3.connect(db_file)
    with con:
        con.execute(
            "INSERT INTO accounts (id, name, profile_arg, profile_path) VALUES (?, ?, ?, ?)",
            (1, "cuenta_uno", "cuenta1", "e:\\tobias\\instagram-bot\\accounts\\cuenta1")
        )
        con.execute(
            "INSERT INTO accounts (id, name, profile_arg, profile_path) VALUES (?, ?, ?, ?)",
            (2, "cuenta_dos", "accounts/cuenta2", "e:\\tobias\\instagram-bot\\accounts\\cuenta2")
        )
    con.close()

    target_accounts = tmp_path / "linux_accounts"
    target_accounts.mkdir()

    # 1. Preview
    preview = migrate_account_paths(db_file, target_accounts, apply=False)
    assert preview["total_accounts"] == 2
    assert preview["accounts_to_update"] == 2
    assert preview["applied"] is False

    # 2. Aplicar migración
    result = migrate_account_paths(db_file, target_accounts, apply=True)
    assert result["applied"] is True
    assert result["accounts_to_update"] == 2

    # Verificar rutas actualizadas
    con = sqlite3.connect(db_file)
    rows = con.execute("SELECT id, profile_path FROM accounts ORDER BY id").fetchall()
    con.close()
    for row in rows:
        assert "e:\\tobias" not in row[1]
        assert str(target_accounts).lower() in row[1].lower()

    # 3. Segunda ejecución: debe ser idempotente (0 cambios)
    repeat = migrate_account_paths(db_file, target_accounts, apply=True)
    assert repeat["accounts_to_update"] == 0

    # 4. Validar integridad post-migración
    val = validate_database(db_file)
    assert val["valid"] is True


def test_database_restore(tmp_path):
    db_file = tmp_path / "original.sqlite3"
    schema_file = Path(__file__).resolve().parents[1] / "database" / "schema.sql"
    init_database(db_file, schema_file)

    # Insertar dato
    con = sqlite3.connect(db_file)
    with con:
        con.execute("INSERT INTO meta (key, value) VALUES ('test_key', 'test_val')")
    con.close()

    # Backup
    backup_file = backup_database(db_file, tmp_path / "backups")

    # Restaurar en una nueva ubicación
    restored_db = tmp_path / "restored.sqlite3"
    restore_database(backup_file, restored_db)

    # Validar
    r_val = validate_database(restored_db)
    assert r_val["valid"] is True

    con = sqlite3.connect(restored_db)
    row = con.execute("SELECT value FROM meta WHERE key='test_key'").fetchone()
    con.close()
    assert row[0] == "test_val"
