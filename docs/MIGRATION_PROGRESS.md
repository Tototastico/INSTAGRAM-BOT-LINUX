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
  - Scripts en `database/scripts/`:
    - `backup_sqlite.py`: Respaldo atómico consistente con SQLite Online Backup API.
    - `validate_database.py`: Comprobación exhaustiva de integridad, quick check, foreign keys y esquemas.
    - `restore_sqlite.py`: Restauración segura con validación bidireccional y copia preventiva.
    - `migrate_paths.py`: Migración transaccional de rutas con vista previa, respaldo previo, comprobación de colisiones e idempotencia.
    - `init_database.py`: Creación limpia de bases de datos desde cero.
  - Documentación en `database/README.md`.
- [ ] **Fase 5 — Despliegue Automatizado VPS**
  - Archivos en `deploy/linux/`: `install.sh`, `deploy.sh`, `update.sh`, `rollback.sh`, `backup.sh`, `healthcheck.sh`, `env.example`.
  - Unidades systemd: `instagram-bot.service`, `instagram-bot-display.service` (Xvfb).
  - Separación de dependencias `requirements-server.txt` sin PyQt5.
- [ ] **Fase 6 — Validaciones y Pruebas**
  - Tests unitarios y de integracion automatizados.
- [ ] **Fase 7 — Documentacion Final**
  - Manuales tecnicos y guias paso a paso.

---

## Archivos modificados en Fase 4:
- `database/scripts/backup_sqlite.py` (nuevo)
- `database/scripts/validate_database.py` (nuevo)
- `database/scripts/restore_sqlite.py` (nuevo)
- `database/scripts/migrate_paths.py` (nuevo)
- `database/scripts/init_database.py` (nuevo)
- `database/README.md` (nuevo)
- `docs/MIGRATION_PROGRESS.md`

## Siguiente paso:
- Iniciar **Fase 5 — Despliegue Automatizado VPS**: generar scripts bash en `deploy/linux/`, unidades systemd, `env.example` y dependencias de servidor `requirements-server.txt`.
