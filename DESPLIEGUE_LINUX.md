# Instagram Bot Linux (Ubuntu 24.04)

Esta carpeta es la version Linux independiente. No copies `accounts/`, `data/`, `.env`, `config.json` ni bases SQLite del proyecto Windows. Los perfiles Windows no son portables: crea perfiles nuevos en Linux e inicia sesion manualmente. El inicio de sesion y el flujo real de comentarios requieren una prueba supervisada antes de uso productivo.

## Instalacion en Hetzner

Los comandos siguientes afectan solo al nuevo servicio. Comprueba antes que el puerto elegido esta libre (`ss -ltn | grep :8000`) y ajusta `/opt/instagram-bot-linux` y el usuario si tu instalacion usa otros nombres. No tocan Docker ni Jarvis.

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip nodejs npm util-linux
# Instala Google Chrome estable para Ubuntu desde su paquete oficial, o Chromium.
google-chrome-stable --version || chromium --version
sudo install -d -o jarvisadmin -g jarvisadmin -m 700 /home/jarvisadmin/instagram-bot-data
sudo install -d -o jarvisadmin -g jarvisadmin -m 755 /opt/instagram-bot-linux
```

Desde una terminal con `rsync` en tu PC (por ejemplo WSL), situado en el directorio padre de ambos proyectos:

```bash
rsync -az --exclude='.git*' --exclude=.env --exclude=accounts --exclude=data --exclude=node_modules --exclude=dist --exclude=__pycache__ --exclude=.pytest_cache --exclude=revisar --exclude='*.zip' --exclude=config.json --exclude=gui_config.json --exclude=crear_cuenta.txt --exclude='*.bat' INSTAGRAM-BOT-LINUX/ jarvisadmin@TU_VPS:/opt/instagram-bot-linux/
```

En el VPS:

```bash
cd /opt/instagram-bot-linux
bash deploy/install.sh
sudo install -d -m 700 /etc/instagram-bot
sudo cp .env.example /etc/instagram-bot/instagram-bot.env
sudo chmod 600 /etc/instagram-bot/instagram-bot.env
sudoedit /etc/instagram-bot/instagram-bot.env
sudo cp deploy/instagram-bot.service /etc/systemd/system/instagram-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now instagram-bot
curl -fsS http://127.0.0.1:8000/api/health
```

Verifica que `CHROME_BINARY` corresponda al ejecutable instalado y que `BOT_PORT` no lo use Jarvis. El servicio usa usuario no root, un worker Uvicorn, un navegador simultaneo y bloqueo `flock` por instancia. `HEADLESS=true` usa Chrome headless con sandbox habilitado. Si Chrome no arranca en tu VPS, diagnostica el error antes de cambiar opciones de sandbox. La primera ejecucion debe usar una base nueva. `config.json` no se importa automaticamente.

Para iniciar sesion manualmente, detene el servicio, abri cada perfil con Chrome bajo `jarvisadmin` y el directorio `BOT_ACCOUNTS_DIR/cuenta1`, inicia sesion, cerra Chrome por completo y luego inicia el servicio. Headless no permite completar desafios interactivos. No abras manualmente un perfil mientras el bot lo usa.

## Operacion y acceso

```bash
sudo systemctl status instagram-bot
sudo journalctl -u instagram-bot -n 100 --no-pager
sudo journalctl -u instagram-bot -f
sudo systemctl stop instagram-bot
sudo systemctl start instagram-bot
```

FastAPI escucha por defecto en `127.0.0.1` y no tiene autenticacion propia. No abras su puerto en el firewall ni uses `0.0.0.0`. Desde Windows, ejecuta `ssh -N -L 18000:127.0.0.1:8000 jarvisadmin@TU_VPS` y abre `http://127.0.0.1:18000/`. Para el celular, usa un tunel SSH del telefono con el mismo reenvio local y abre la URL local en el navegador del telefono. Una alternativa es una VPN privada como Tailscale, manteniendo el panel unido a loopback y usando un tunel SSH por esa red. Un dominio publico requiere proxy HTTPS, autenticacion y proteccion CSRF antes de exponerse.

## Actualizacion, respaldo y restauracion

Antes de actualizar, espera o cancela las tareas activas y detene el servicio. Copia SQLite consistentemente:

```bash
cd /opt/instagram-bot-linux
sudo -u jarvisadmin .venv/bin/python -m deploy.backup /home/jarvisadmin/instagram-bot-backups
```

Con Chrome cerrado, respalda `BOT_ACCOUNTS_DIR` en un archivo privado si necesitas conservar sesiones; trata ese respaldo como credenciales. Para actualizar, copia el codigo nuevo con las mismas exclusiones, ejecuta `bash deploy/install.sh` y reinicia el servicio. Conserva el release anterior para volver atras.

Para restaurar, detene el servicio, copia el backup SQLite elegido a `BOT_DB_PATH`, asigna propiedad `jarvisadmin`, permisos `0600`, y reinicia. No sobreescribas perfiles mientras Chrome esta activo. Las tareas interrumpidas requieren reanudacion manual; un clic registrado no confirma que Instagram haya publicado el comentario.

Si restauras una base del proyecto Windows, respalda primero y recalcula las rutas de perfiles con `sudo -u jarvisadmin .venv/bin/python -m deploy.migrate_profiles` para ver la propuesta y luego con `--apply`. Crea los perfiles nuevos en Linux; la migracion solo cambia rutas en SQLite.

## Validacion pendiente en Ubuntu

Instala dependencias de prueba con `.venv/bin/python -m pip install -r requirements-web.txt` y ejecuta `.venv/bin/python -m pytest -q`, `npm ci && npm run build`, `/api/health`, y una apertura/cierre de Chrome con perfil descartable. Despues, verifica login manual, pausa/cancelacion y un comentario en una publicacion propia o autorizada. Mide RAM y CPU en el VPS antes de aumentar `MAX_CONCURRENT_BROWSERS`.
