# Guía de Despliegue de INSTAGRAM-BOT

## 1. Despliegue Inicial
Una vez ejecutado `install.sh`, el despliegue del release se realiza con:

```bash
sudo ./deploy/linux/deploy.sh
```

El script `deploy.sh`:
1. Crea un nuevo directorio en `/opt/instagram-bot/releases/<TIMESTAMP>`.
2. Copia el código fuente excluyendo perfiles, venvs y bases locales.
3. Instala las dependencias en `/opt/instagram-bot/venv` usando `requirements-server.txt` (sin PyQt5).
4. Compila el frontend React/Vite (`npm ci && npm run build`).
5. Verifica o inicializa la base de datos persistente en `/var/lib/instagram-bot/data/bot.sqlite3`.
6. Conmuta el symlink `/opt/instagram-bot/current` al nuevo release.
7. Reinicia los servicios de display y backend.
8. Ejecuta comprobaciones automáticas con `healthcheck.sh`.

---

## 2. Servicios Systemd
El bot se gestiona mediante dos unidades systemd:

- `instagram-bot-display.service`: Gestiona Xvfb en la pantalla `:99` (`1366x768x24`).
- `instagram-bot.service`: Servidor Uvicorn (`127.0.0.1:8000`, 1 worker, single-instance lock).

### Comandos de Control:
```bash
# Ver estado
sudo systemctl status instagram-bot.service
sudo systemctl status instagram-bot-display.service

# Reiniciar
sudo systemctl restart instagram-bot.service

# Ver logs en tiempo real
sudo journalctl -u instagram-bot.service -f
sudo journalctl -u instagram-bot-display.service -f
```

---

## 3. Acceso Seguro al Dashboard por Túnel SSH
El servidor Uvicorn escucha **únicamente en 127.0.0.1:8000** y no está expuesto a Internet.
Para abrir el panel web en tu navegador local:

```bash
# En tu computadora local (PowerShell o Terminal Linux/Mac):
ssh -N -L 18000:127.0.0.1:8000 usuario@IP_DEL_VPS
```

Una vez establecido el túnel, abre tu navegador en:
`http://localhost:18000`
