# Progression de Migracion a Linux VPS

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
- [ ] **Fase 3 — Motor y Coordinacion**
  - Bloqueo exclusivo de instancia (single process lock con `fcntl.flock` en Linux y `msvcrt` en Windows).
  - Cierre ordenado con `lifespan` en FastAPI (rechazo de nuevas tareas, espera segura, cierre de navegadores `driver.quit()`).
  - Persistencia y recuperacion segura de tareas interrumpidas.
- [ ] **Fase 4 — Base de Datos**
  - Scripts en `database/scripts/`: `backup_sqlite.py`, `migrate_paths.py`, `validate_database.py`, `restore_sqlite.py`.
  - Soporte de instalacion nueva y migracion segura Windows -> Linux.
- [ ] **Fase 5 — Despliegue Automatizado VPS**
  - Archivos en `deploy/linux/`: `install.sh`, `deploy.sh`, `update.sh`, `rollback.sh`, `backup.sh`, `healthcheck.sh`, `env.example`.
  - Unidades systemd: `instagram-bot.service`, `instagram-bot-display.service` (Xvfb).
- [ ] **Fase 6 — Validaciones y Pruebas**
  - Tests unitarios y de integracion automatizados para rutas, bloqueo y migracion.
- [ ] **Fase 7 — Documentacion Final**
  - Manuales tecnicos y guias paso a paso.

---

## Archivos modificados en Fase 2:
- `webapp/paths.py` (nuevo)
- `webapp/chrome_binary.py`
- `webapp/db.py`
- `selenium_runner.py`
- `docs/MIGRATION_PROGRESS.md`

## Siguiente paso:
- Iniciar **Fase 3 — Motor y Coordinación**: implementar bloqueo exclusivo de instancia (`flock`/`msvcrt`), apagado ordenado FastAPI lifespan con drenado de tareas activas y cierre de drivers.
