# Progreso de Migracion a Linux VPS

**Rama:** `feat/linux-vps-migration`  
**Commit base:** `e6f5f7732b20cbb1cd41f738309c25dca07ef8a0`  
**Ultima actualizacion:** 2026-10-27  

---

## Estado de las Fases

- [x] **Fase 1 — Git y Auditoria Inicial**
  - Branch aislada `feat/linux-vps-migration` creada sin tocar `main`.
  - `.gitignore` robustecido para proteger SQLite, cuentas, perfiles, sesiones y zips.
  - Esquema SQLite auditado e inmortalizado en `database/schema.sql`.
  - Documento de auditoria generado en `docs/MIGRATION_AUDIT.md`.
  - Tests base existentes validados (13/13 pasados).
- [x] **Fase 2 — Compatibilidad Multiplataforma**
  - Normalizacion centralizada de rutas en `webapp/paths.py` con variables de entorno (`INSTAGRAM_ACCOUNTS_DIR`, `INSTAGRAM_BOT_DB_PATH`, `INSTAGRAM_BOT_CHROME_BINARY`).
  - Deteccion de Chrome para Linux (`--version` via subprocess) y Windows (`ctypes.WinDLL`) en `webapp/chrome_binary.py`.
  - Adaptacion de `selenium_runner.py` con resolucion centralizada de perfil y flags adecuados para Linux/Xvfb (sandbox no-root, visual).
  - Integracion de `webapp/db.py` con `webapp/paths.py`.
- [x] **Fase 3 — Motor y Coordinacion**
  - Bloqueo exclusivo de instancia única de proceso (`SingleInstanceLock` con `flock` en Linux y `msvcrt` en Windows) en `webapp/instance_lock.py`.
  - Cierre ordenado con `lifespan` en FastAPI (`webapp/api.py`), rechazando nuevas tareas y liberando el bloqueo de proceso.
  - `Coordinator.shutdown(timeout_seconds=15)` con drenado de hilos, marcado seguro en base de datos (`interrupted`) y cierre forzado de navegadores Selenium (`runner.close()`).
- [x] **Fase 4 — Base de Datos**
  - Scripts en `database/scripts/`: `backup_sqlite.py`, `validate_database.py`, `restore_sqlite.py`, `migrate_paths.py`, `init_database.py`.
  - Soporte de instalacion nueva y migracion segura Windows -> Linux.
- [x] **Fase 5 — Despliegue Automatizado VPS**
  - Dependencias de servidor `requirements-server.txt` sin PyQt5.
  - Configuración de entorno `deploy/linux/env.example`.
  - Unidades systemd: `instagram-bot.service` y `instagram-bot-display.service` (Xvfb).
  - Scripts bash completos: `install.sh`, `deploy.sh`, `update.sh`, `rollback.sh`, `backup.sh`, `healthcheck.sh`.
- [x] **Fase 6 — Validaciones y Pruebas**
  - Tests unitarios y de integración para rutas, Chrome detection, DB backup/restore/migration, lock y lifespan en `tests/test_migration_and_platform.py`.
- [x] **Fase 7 — Documentacion Final**
  - `docs/MIGRATION_AUDIT.md`
  - `docs/LINUX_INSTALLATION.md`
  - `docs/DATABASE_MIGRATION.md`
  - `docs/DEPLOYMENT.md`
  - `docs/UPDATE_AND_ROLLBACK.md`
  - `docs/WINDOWS_COMPATIBILITY.md`
  - `docs/SECURITY.md`
  - `docs/TESTING.md`

---

## Archivos modificados en Fase 7:
- `docs/LINUX_INSTALLATION.md` (nuevo)
- `docs/DEPLOYMENT.md` (nuevo)
- `docs/DATABASE_MIGRATION.md` (nuevo)
- `docs/UPDATE_AND_ROLLBACK.md` (nuevo)
- `docs/WINDOWS_COMPATIBILITY.md` (nuevo)
- `docs/SECURITY.md` (nuevo)
- `docs/TESTING.md` (nuevo)
- `docs/MIGRATION_PROGRESS.md`

## Estado:
- **Migración técnica completa y lista para ser validada en el repositorio.**
