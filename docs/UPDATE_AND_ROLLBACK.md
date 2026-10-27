# Guía de Actualización y Rollback

---

## 1. Actualización Controlada (`update.sh`)
Para actualizar a una versión más reciente sin perder tareas activas ni comprometer la base de datos:

```bash
cd /opt/instagram-bot/repo
git pull origin feat/linux-vps-migration

sudo ./deploy/linux/update.sh
```

El script ejecuta:
1. Respaldo atómico de la base SQLite activa.
2. Detención ordenada de `instagram-bot.service` (drena tareas en curso).
3. Creación de un nuevo directorio de release.
4. Instalación de nuevas dependencias de servidor.
5. Recompilación del frontend (`npm run build`).
6. Validación de la base persistente.
7. Conmutación del enlace `/opt/instagram-bot/current`.
8. Comprobación integral mediante `healthcheck.sh`.

---

## 2. Reversión Rápida (`rollback.sh`)
Si una actualización presenta anomalías, puedes regresar al release anterior en segundos:

```bash
sudo ./deploy/linux/rollback.sh
```

El script:
1. Identifica el release inmediatamente anterior en `/opt/instagram-bot/releases/`.
2. Detiene el servicio Uvicorn.
3. Apunta `/opt/instagram-bot/current` al release previo.
4. Reinicia los servicios.
5. Ejecuta `healthcheck.sh`.

---

## 3. Restauración de Base de Datos ante Contingencias
Si una actualización requirió cambios de datos que debas revertir:

```bash
# Listar backups disponibles:
ls -lh /var/lib/instagram-bot/backups/

# Restaurar el backup verificado:
sudo -u instagram-bot /opt/instagram-bot/venv/bin/python /opt/instagram-bot/current/database/scripts/restore_sqlite.py \
    --backup /var/lib/instagram-bot/backups/bot_20261027_120000.sqlite3 \
    --target /var/lib/instagram-bot/data/bot.sqlite3
```
