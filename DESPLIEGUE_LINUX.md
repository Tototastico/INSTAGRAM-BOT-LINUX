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

## Monitoreo visual y diagnosticos de Selenium

`HEADLESS=true` conserva el arranque normal. Para ver Chrome en el Xvfb existente, configura `HEADLESS=false`, `DISPLAY=:99` y `XAUTHORITY` con la ruta **real** del archivo de autorizacion X11. El usuario `jarvisadmin` debe poder leer ese archivo. Chrome hereda ambas variables tanto de systemd (`EnvironmentFile`) como de la terminal manual. No se crean perfiles de cuentas nuevos durante la prueba visual: el verificador usa un perfil temporal fuera de `BOT_ACCOUNTS_DIR`.

Configura tambien `BOT_DEBUG_DIR=/home/jarvisadmin/instagram-bot-data/debug`, `BOT_DEBUG_RETENTION_DAYS=7` y un token aleatorio privado `BOT_DIAGNOSTICS_TOKEN`. Genera el valor con `.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'` y pegalo mediante `sudoedit /etc/instagram-bot/instagram-bot.env`. No incluyas comillas ni publiques el token. Con token ausente, los endpoints de diagnostico devuelven 503. El panel pide el token al abrir la seccion **Diagnostico** de una tarea; lo mantiene solo en memoria del navegador. Las capturas se sirven con `X-Diagnostics-Token`, vinculadas al ID de la tarea, y no se guardan en cache. La carpeta y las capturas usan permisos 0700/0600; los registros y PNG anteriores a siete dias se eliminan al generar o consultar diagnosticos.

El diagnostico registra etapa, tipo de error, URL sin query ni fragmento, titulo (oculto en login), estado de carga, respuesta del navegador y numero de elementos visibles. No guarda HTML, cookies, cabeceras ni el texto crudo de excepciones de Selenium. No toma capturas de login, challenge o checkpoint. Una captura de una publicacion puede contener informacion de la cuenta: conserva el token y los backups como secretos. Los endpoints generales del panel siguen siendo locales y deben usarse solo por tunel SSH.

Para actualizar esta version en Hetzner sin tocar Jarvis ni Nginx:

```bash
sudo systemctl stop instagram-bot
cd /opt/instagram-bot-linux
sudo -u jarvisadmin env BOT_DB_PATH=/home/jarvisadmin/instagram-bot-data/bot.sqlite3 .venv/bin/python -m deploy.backup /home/jarvisadmin/instagram-bot-backups
# Desde la PC, ejecuta el rsync de la seccion Instalacion, excluyendo datos y perfiles.
bash deploy/install.sh
sudoedit /etc/instagram-bot/instagram-bot.env
sudo systemctl restart instagram-bot
curl -fsS http://127.0.0.1:8000/api/health
```

Para comprobar la pantalla sin abrir Instagram ni modificar sesiones, instala `xdotool` (`sudo apt install -y xdotool`). Con el servicio y VNC existentes, ejecuta:

```bash
cd /opt/instagram-bot-linux
sudo -u jarvisadmin env HEADLESS=false DISPLAY=:99 XAUTHORITY=/RUTA/REAL/.Xauthority CHROME_BINARY=/usr/bin/google-chrome-stable BOT_DATA_DIR=/home/jarvisadmin/instagram-bot-data .venv/bin/python -m deploy.verify_visual
```

El script abre durante 30 segundos una pagina `data:` con el texto "Chrome controlado por Selenium", comprueba que X11 informa una ventana Chrome visible y luego cierra el navegador temporal. Desde tu PC, abre un tunel separado `ssh -N -L 5901:127.0.0.1:5901 jarvisadmin@TU_VPS` y conecta tu visor VNC a `127.0.0.1:5901`. Si el visor no muestra esa ventana, comprueba que VNC y el comando usan el mismo `DISPLAY`, y revisa `XAUTHORITY`; no expongas el puerto VNC a Internet. Despues de la prueba, deja `HEADLESS=true` o cambia a `false` en el archivo de entorno y reinicia solo `instagram-bot`.

Un timeout de busqueda del editor ocurre cuando `WebDriverWait` no encuentra un campo de comentario visible y habilitado. El diagnostico distingue redireccion al login, verificacion, publicacion inaccesible, carga incompleta, selector ausente, elemento no interactuable, dialogo superpuesto y navegador sin respuesta. No aumenta el tiempo de espera ni intenta superar verificaciones de Instagram.

### Analisis de la tarea #4 y comprobacion supervisada

La evidencia de la tarea #4 (14 de noviembre de 2026) muestra que la publicacion cargo, `document.readyState` estaba en `complete`, Chrome respondia y el editor "Add a comment..." era visible en la captura. El error se registro en `page_ready`, **antes** de ejecutar el selector del editor. En la version anterior, esa etapa hacia `maximize_window()`, cambiaba el foco, buscaba `body` y ejecutaba clics sobre la pagina. El registro anterior solo conservo `WebDriverException`, por lo que no permite determinar cual de esas operaciones fallo. No atribuir este incidente al selector ni declararlo resuelto por la captura.

La version actual espera `document.readyState == complete` y busca directamente un editor identificado por atributos semanticos (`aria-label`, `placeholder`, `aria-placeholder`, `data-placeholder` o `name`), admitiendo `textarea`, `input` y `contenteditable`. Antes de escribir, comprueba editabilidad, visibilidad, habilitacion y foco. No hace clic general en `body`, no maximiza la ventana ni presupone un modal. Si falla, el diagnostico autenticado muestra la etapa, operacion, condicion, selector, tipo y **mensaje completo de Selenium con datos sensibles ocultos**. Las capturas conservan la politica privada de retencion configurada.

Despues de actualizar el servicio, realiza una sola prueba supervisada en una publicacion propia o autorizada, con VNC privado y una cuenta cuyo perfil no este abierto en otro Chrome. Observa que el foco llegue al editor correcto antes de permitir el envio. Si falla, abre **Diagnostico** en la nueva tarea y comparte el ID, `Operacion`, `Condicion` y `Mensaje tecnico` ocultando cualquier dato de la cuenta. No reanudes la tarea #4 automaticamente ni consideres confirmado un comentario solo por el clic en Publicar.

### Analisis de la tarea #5: boton Post visible, XPath en espanol

La tarea #5 del 14 de noviembre de 2026 llego a escribir el comentario. El selector usado entonces era exactamente `//div[@role="button" and text()="Publicar"]`; la captura muestra el control **Post**. Esa diferencia de idioma explica el `TimeoutException` en `publish_button_lookup`. El `StaleElementReferenceException` anterior fue durante la busqueda del editor y se recupero; no demuestra que el boton estuviera obsoleto. El contador de comentarios no disponible es independiente. No se dispone del DOM real del VPS para confirmar el elemento HTML exacto ni el resultado de un clic.

El localizador actual busca controles `button`, `[role="button"]` e `input[type="submit"]` con etiqueta exacta `Post` o `Publicar`. Busca de nuevo el editor tras escribir, comprueba que sigue activo y que contiene el texto esperado **sin registrar ese texto**, y selecciona un unico control visible y habilitado dentro de su formulario o un ancestro cercano. Vuelve a comprobarlo inmediatamente antes de hacer un solo clic. Si el DOM cambia o la relacion editor/boton no es clara, se detiene. Un error durante el comando de clic deja la cuenta en pausa para revision manual porque el resultado puede ser incierto; no se reintenta el envio automaticamente.

El panel muestra si el control estaba ausente, oculto, deshabilitado, ambiguo o si hubo referencias obsoletas. Guarda solo una representacion estructural depurada del editor y el control (etiquetas, rol, estado y `Post`/`Publicar`), sin `outerHTML`, clases, valores del campo, cookies ni datos de la cuenta. La captura de error mantiene los permisos y retencion privados. Las pruebas locales usan HTML con un editor y boton reemplazados dinamicamente; la confirmacion final requiere una prueba supervisada en el VPS con una publicacion propia o autorizada. No reanudes automaticamente la tarea #5, que conserva un comentario sin publicar en su editor hasta revisar el perfil.

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
