# Progreso de Migración a Linux VPS

**Rama:** `feat/linux-vps-migration`  
**Commit base:** `e6f5f7732b20cbb1cd41f738309c25dca07ef8a0`  
**Última actualización:** 2026-10-27  

---

## Estado de las Fases

- [x] **Fase 1 — Git y Auditoría Inicial**
  - Branch aislada `feat/linux-vps-migration` creada sin tocar `main`.
  - `.gitignore` robustecido para proteger SQLite, cuentas, perfiles, sesiones y zips.
  - Esquema SQLite auditado e inmortalizado en `database/schema.sql`.
  - Documento de auditoría generado en `docs/MIGRATION_AUDIT.md`.
  - Tests base existentes ejecutados y validados (13/13 pasaron en 2.63s).
- [ ] **Fase 2 — Compatibilidad Multiplataforma**
  - Normalización de rutas con `Path` y variables de entorno (`INSTAGRAM_ACCOUNTS_DIR`, `INSTAGRAM_BOT_DB_PATH`, `INSTAGRAM_BOT_CHROME_BINARY`).
  - Detección de Chrome para Linux y Windows en `webapp/chrome_binary.py`.
  - Adaptación de `selenium_runner.py` para usar la resolución centralizada de perfiles y sandbox no-root en Linux.
- [ ] **Fase 3 — Motor y Coordinación**
  - Bloqueo exclusivo de instancia (single process lock con `fcntl.flock` en Linux y fallback seguro en Windows).
  - Bloqueo de perfiles robustecido.
  - Cierre ordenado con `lifespan` en FastAPI (rechazo de nuevas tareas, espera segura, cierre de navegadores `driver.quit()`).
- [ ] **Fase 4 — Base de Datos**
  - Scripts en `database/scripts/`: `backup_sqlite.py`, `migrate_paths.py`, `validate_database.py`, `restore_sqlite.py`.
  - Soporte de instalación nueva y migración segura Windows -> Linux.
- [ ] **Fase 5 — Despliegue Automatizado VPS**
  - Archivos en `deploy/linux/`: `install.sh`, `deploy.sh`, `update.sh`, `rollback.sh`, `backup.sh`, `healthcheck.sh`, `env.example`.
  - Unidades systemd: `instagram-bot.service`, `instagram-bot-display.service` (Xvfb).
- [ ] **Fase 6 — Validaciones y Pruebas**
  - Tests automatizados multiplataforma (rutas, Chrome detection, DB backup/restore/migration, lock, lifespan).
- [ ] **Fase 7 — Documentación Final**
  - `LINUX_INSTALLATION.md`, `DATABASE_MIGRATION.md`, `DEPLOYMENT.md`, `UPDATE_AND_ROLLBACK.md`, `WINDOWS_COMPATIBILITY.md`, `SECURITY.md`, `TESTING.md`.

---

## Archivos modificados en Fase 1:
- `.gitignore`
- `database/schema.sql` (nuevo)
- `docs/MIGRATION_AUDIT.md` (nuevo)
- `docs/MIGRATION_PROGRESS.md` (nuevo)

## Siguiente paso:
- Iniciar **Fase 2 — Compatibilidad Multiplataforma**: configurar resolución centralizada de rutas y adaptar `webapp/chrome_binary.py` y `selenium_runner.py`.
