# Migracion a Linux y despliegue en un VPS

Estado: propuesta de trabajo, no implementada. Fecha: 27 de octubre de 2026.

Este documento parte del estado actual del repositorio. Asume un VPS Ubuntu x86-64, una sola instancia de la aplicacion, Google Chrome instalado desde una fuente oficial, y acceso privado al panel por tunel SSH. No presupone que los perfiles de Chrome de Windows funcionen en Linux ni que el envio real haya sido probado alli.

## 1. Lo que hoy impide ejecutarlo en Linux

| Lugar | Estado actual | Cambio necesario |
| --- | --- | --- |
| `selenium_runner.py` | Arma `E:/tobias/INSTAGRAM-BOT/accounts/{nombre_cuenta}`. | Obtener la ruta desde una configuracion comun y usar `pathlib.Path`; no alterar el orden de navegacion, tipeo y clic. |
| `webapp/chrome_binary.py` | Usa `ctypes.WinDLL('version')`, disponible solo en Windows. | Mantener esa rama para Windows y agregar una rama Linux que ejecute `chrome --version`, valide el resultado y entregue `(ruta_binario, version_principal)` al mismo `uc.Chrome(...)`. |
| `webapp/db.py` | `profile_path()` convierte toda la ruta a minusculas. | Conservar mayusculas/minusculas en Linux; usar normalizacion dependiente del sistema. El mismo `profile_path()` debe ser la fuente de verdad para la ruta que usa Chrome y la clave de exclusion del coordinador. |
| `webapp/db.py` y `actualizar_rutas.py` | La base esta bajo `ROOT/data`; el script de migracion presupone `data/bot.sqlite3`. | Permitir `INSTAGRAM_BOT_DB_PATH` y adaptar el script para recibir ruta de base y carpeta de perfiles; validar y respaldar antes de actualizar filas. |
| `requirements.txt` | Incluye PyQt5 aunque el VPS solo usa el panel web. | Separar dependencias de escritorio y servidor; fijar versiones comprobadas en un lock o imagen reproducible. |
| `webapp/coordinator.py` y `webapp/api.py` | Bloqueos por perfil en memoria; hilos daemon; `lifespan` no cierra tareas. | Un solo proceso de API, bloqueo de instancia, apagado ordenado y cierre de navegadores. No activar `--workers > 1` ni `--reload`. |
| `tests/test_chrome_version.py` y documentacion | Pruebas y README suponen rutas de Windows. | Parametrizar las pruebas por plataforma y documentar ambos arranques. |

El cambio de ruta necesita una prueba especifica: `cuenta1` y `accounts/cuenta1` deben resolver al mismo directorio Linux, sin crear `accounts/accounts/cuenta1`. En Linux, `Cuenta1` y `cuenta1` no se deben fusionar silenciosamente porque el sistema de archivos distingue esos nombres.

## 2. Cambios del motor antes de desplegar

1. **Unificar rutas.** Definir `INSTAGRAM_ACCOUNTS_DIR=/var/lib/instagram-bot/accounts` y hacer que `crear_driver()` use la ruta resuelta por `webapp.db.profile_path(profile_arg)`. Conservar el argumento `profile_arg` en la base para no romper asignaciones existentes. Validar que el directorio esperado exista antes de abrir Chrome y mostrar un error claro si falta.
2. **Detectar Chrome en ambas plataformas.** En Windows conservar la lectura de version del ejecutable. En Linux buscar `INSTAGRAM_BOT_CHROME_BINARY` o un binario reconocido, ejecutar `--version` sin shell, extraer y validar el numero principal. Pasar siempre ese mismo binario y `version_main` a `uc.Chrome`. Probar el par Chrome/ChromeDriver instalado antes de usar una cuenta. [ChromeDriver exige compatibilidad de versiones](https://developer.chrome.com/docs/chromedriver/downloads/version-selection); [Selenium documenta las opciones de binario y `--user-data-dir`](https://www.selenium.dev/documentation/webdriver/browsers/chrome/).
3. **Preservar el comportamiento visual primero.** Ejecutar Chrome con pantalla virtual Xvfb, inicialmente sin `--headless`, para comparar con el flujo actual. Verificar `maximize_window()`, el selector del textarea y el clic de Publicar en una prueba supervisada. Solo considerar `--headless=new` despues de repetir esas pruebas; [Selenium lo soporta](https://www.selenium.dev/documentation/webdriver/browsers/chrome/), pero puede cambiar el comportamiento observable de la pagina. Ejecutar Chrome como usuario no root y probar con sandbox habilitado; quitar el `--no-sandbox` de la ruta Linux y no depender del valor por defecto de `undetected-chromedriver`.
4. **Cerrar ordenadamente.** En el `lifespan` de FastAPI, dejar de aceptar tareas nuevas al recibir parada, esperar a que termine la accion en curso dentro de un plazo configurado, persistir `interrupted` si corresponde y llamar `driver.quit()`. El servicio debe esperar ese plazo antes de terminar el proceso. No reintentar automaticamente un comentario cuyo resultado quedo incierto.
5. **Bloquear una sola instancia.** El diccionario `active_profiles` solo protege hilos del mismo proceso. Añadir un bloqueo de proceso en Linux y mantener Uvicorn con un worker. Cualquier futuro despliegue con varios workers o replicas requerira mover coordinacion y bloqueo a un servicio compartido; SQLite por si sola no resuelve esa exclusion.
6. **Separar instalacion de escritorio.** Crear un conjunto de dependencias de servidor sin PyQt5. Mantener `GUI.py` y `main.py` como herramientas locales de Windows, fuera del servicio Linux. Compilar `frontend` con `npm ci && npm run build`; la API ya sirve `frontend/dist` y el frontend usa rutas `/api` relativas.

Antes de cambiar el motor, guardar una prueba de referencia de sus llamadas: `acceder_caja(url, perfil)` seguido por `comentar_en_post(texto, driver, textarea)`. El nuevo arranque Linux debe cambiar solo la preparacion del navegador y las rutas; la interaccion con la publicacion se valida aparte.

## 3. Datos y perfiles al migrar

- **Base SQLite:** generar una copia consistente con la [API de backup de SQLite](https://sqlite.org/backup.html), no copiar solo `bot.sqlite3` mientras el servicio escribe: en modo WAL tambien existen archivos `-wal` y `-shm` que forman parte del estado activo. [Referencia WAL](https://www.sqlite.org/wal.html). Conservar una copia fechada fuera del directorio de releases.
- **Rutas en la base:** despues de transferir la copia al VPS, ejecutar una migracion con vista previa y respaldo que recalcule `accounts.profile_path` a partir de `profile_arg` y `INSTAGRAM_ACCOUNTS_DIR`. Verificar colisiones, directorios faltantes y asignaciones antes de confirmar. `actualizar_rutas.py` debe aceptar parametros y no depender del directorio de trabajo.
- **Sesiones de Chrome:** crear perfiles nuevos en Linux y hacer el inicio de sesion manual alli. No asumir que copiar `accounts/` desde Windows conserva cookies o credenciales: [Chromium usa mecanismos de almacenamiento y cifrado dependientes del sistema operativo](https://chromium.googlesource.com/chromium/src/%2B/HEAD/docs/security/faq.md). Usar un directorio distinto por cuenta, permisos `0700` y el mismo usuario Linux para el login manual y el servicio. [Chromium advierte que dos Chrome no pueden compartir simultaneamente un directorio de datos](https://chromium.googlesource.com/chromium/src/%2B/HEAD/docs/user_data_dir.md).
- **Estado de tareas:** antes de exportar, pausar o cancelar las tareas activas y registrar sus IDs. Tras el primer arranque Linux, revisar las tareas `interrupted` manualmente; no reanudarlas en masa. No importar `config.json` de Windows sobre una base ya migrada.
- **Secretos y respaldos:** mantener perfiles, base y respaldos fuera de Git, accesibles solo al usuario del servicio. No guardar contraseñas en `config.json`, variables de entorno versionadas ni logs.

## 4. Despliegue inicial recomendado

### Preparar el VPS

1. Crear un usuario de servicio sin privilegios, por ejemplo `instagram-bot`, con directorio de estado `/var/lib/instagram-bot`. Crear `/var/lib/instagram-bot/accounts`, `/var/lib/instagram-bot/data` y `/opt/instagram-bot`; dar propiedad al usuario de servicio y permisos restringidos. Reservar RAM y disco segun el numero **real** de Chrome simultaneos; medir primero con una cuenta.
2. Instalar Python 3, `venv`, Xvfb, un gestor de ventanas liviano si `maximize_window()` lo requiere, y Google Chrome estable para Linux x86-64. Instalar Node LTS solo para compilar el frontend, o transferir un `dist` construido y verificado. Confirmar `google-chrome --version` y la arquitectura antes de instalar dependencias Python.
3. Copiar una version identificable del codigo a `/opt/instagram-bot`, crear `.venv`, instalar las dependencias de servidor fijadas y ejecutar `npm ci && npm run build` en `frontend` si se compila en el VPS. No incluir `node_modules`, `data/` ni perfiles dentro del release.
4. Definir un archivo de entorno legible solo por root y el servicio, por ejemplo `/etc/instagram-bot/instagram-bot.env`:

   ```ini
   INSTAGRAM_ACCOUNTS_DIR=/var/lib/instagram-bot/accounts
   INSTAGRAM_BOT_DB_PATH=/var/lib/instagram-bot/data/bot.sqlite3
   INSTAGRAM_BOT_CHROME_BINARY=/usr/bin/google-chrome-stable
   DISPLAY=:99
   HOME=/var/lib/instagram-bot
   ```

   `INSTAGRAM_BOT_DB_PATH` es una interfaz **a implementar** en el repositorio; el archivo de entorno no tendra efecto para la base hasta que se haga el cambio de la seccion 2.

### Pantalla virtual y servicio

Mantener una pantalla Xvfb persistente en `:99` mediante una unidad `instagram-bot-display.service` que ejecute `/usr/bin/Xvfb :99 -screen 0 1366x768x24 -nolisten tcp` como el usuario de servicio. Si la prueba visual lo requiere, iniciar un gestor de ventanas ligero en ese display mediante otra unidad. La pantalla no debe escuchar conexiones de red.

Unidad de aplicacion de referencia, a crear **despues** de implementar el apagado ordenado:

```ini
[Unit]
Description=INSTAGRAM-BOT local web
After=network-online.target instagram-bot-display.service
Requires=instagram-bot-display.service

[Service]
Type=simple
User=instagram-bot
Group=instagram-bot
WorkingDirectory=/opt/instagram-bot
EnvironmentFile=/etc/instagram-bot/instagram-bot.env
RuntimeDirectory=instagram-bot
ExecStart=/usr/bin/flock -n /run/instagram-bot/instance.lock /opt/instagram-bot/.venv/bin/python -m uvicorn webapp.api:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5
TimeoutStopSec=90
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Instalar las unidades en `/etc/systemd/system/`, ejecutar `systemctl daemon-reload`, habilitar e iniciar primero la pantalla y luego la aplicacion. Revisar `systemctl status instagram-bot` y `journalctl -u instagram-bot -f`. `Restart=on-failure` y `ExecStart` siguen la [documentacion de systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html). No usar `--reload`, varios workers ni dos copias del servicio sobre los mismos perfiles.

### Acceso al panel

La API actual **no tiene autenticacion** y sus rutas permiten iniciar tareas. Mantener Uvicorn unido a `127.0.0.1`, no abrir el puerto 8000 en el firewall y entrar desde la PC mediante un [tunel local SSH](https://man.openbsd.org/ssh):

```bash
ssh -N -L 18000:127.0.0.1:8000 usuario@vps
```

Abrir `http://127.0.0.1:18000/` en la PC. No publicar este panel con `--host 0.0.0.0`. Si mas adelante se necesita acceso publico, primero implementar autenticacion, proteccion de sesiones/CSRF, HTTPS y una politica de acceso; recien entonces colocar un proxy inverso. [Nginx documenta `proxy_pass` para ese escenario](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

Para iniciar sesion en las cuentas, usar temporalmente un escritorio remoto conectado al display virtual **solo por tunel SSH**, sin exponer VNC/RDP a Internet. Detener cualquier tarea de ese perfil antes de abrir Chrome manualmente; cerrar el navegador manual antes de que el servicio use el mismo directorio.

## 5. Validacion y puesta en marcha

1. En Windows, mantener verde la suite existente y agregar pruebas de deteccion de version en Linux, rutas sensibles a mayusculas, `cuenta1` frente a `accounts/cuenta1`, y migracion de `profile_path`. Ninguna prueba debe publicar en Instagram.
2. En un Linux de prueba, ejecutar `pytest`, compilar el frontend y abrir una sesion Chrome/ChromeDriver con perfil descartable. Comprobar que `driver.quit()` no deja el perfil bloqueado. Confirmar que `maximize_window()` y el textarea se comportan como en Windows.
3. Iniciar el servicio con base nueva o copia migrada. Comprobar `/`, `/assets/...`, `/api/overview`, permisos de archivos, y acceso solo por tunel. Verificar que un segundo proceso no arranca por el bloqueo de instancia.
4. Crear una sola cuenta Linux y una asignacion corta. Hacer una prueba supervisada con un sorteo propio o autorizado; comparar el comentario y el resultado visible. Un clic registrado sigue sin equivaler a publicacion confirmada.
5. Probar dos sorteos del mismo perfil: deben quedar en cola, nunca abrir dos Chrome sobre esa carpeta. Probar otro perfil en paralelo solo despues de medir RAM/CPU. Validar pausa, cancelacion, error de login y reinicio del servicio; revisar que las tareas inciertas queden `interrupted` y requieran accion manual.
6. Respaldar la base con la API de SQLite y probar una restauracion en una ubicacion separada. Respaldar perfiles solo con Chrome cerrado y proteger esos respaldos como credenciales.

## 6. Actualizaciones y vuelta atras

Antes de actualizar: detener nuevas tareas, esperar o cancelar las activas, hacer copia consistente de la base, anotar la version del codigo y conservar el release anterior. Construir y probar el nuevo release sin usar perfiles reales. Detener el servicio, instalar el nuevo codigo, ejecutar cualquier migracion de esquema/rutas con respaldo y reiniciar una sola instancia.

Si falla: detener el servicio, restaurar el release anterior y la copia de base correspondiente, verificar las rutas de perfiles y reiniciar. No restaurar un perfil de Chrome mientras haya procesos usandolo. Las tareas que pudieran haber hecho clic antes del corte se revisan manualmente antes de reanudarse. El rollback de codigo **no** garantiza rollback de comentarios ya publicados.

## Criterio para considerar listo el VPS

El despliegue esta listo solo cuando: las rutas y la deteccion de Chrome funcionan en Linux, el servidor corre como usuario no root y un solo proceso, el panel no es publico, los perfiles se crearon en Linux, se probó el apagado/reinicio sin duplicar tareas, existe backup restaurable, y una prueba supervisada confirma el flujo real de comentario.
