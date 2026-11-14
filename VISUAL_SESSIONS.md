# Cuentas visuales y acceso móvil

## Estado y límites

La función está implementada en la rama `feature/account-visual-login-mobile` y probada con mocks y un navegador local; falta validarla en el VPS con una cuenta de prueba y un certificado TLS válido. No se modificaron Nginx, systemd, VNC, perfiles reales ni sesiones del VPS desde este workspace.

El VNC actual de `DISPLAY=:99` es compartido. Exponerlo en el dashboard permitiría ver otra cuenta. Cada inicio visual crea un Xvfb privado (`:120` a `:179`), un archivo XAUTHORITY temporal, un `x11vnc` que escucha solo en `127.0.0.1` y un Chrome con el perfil existente como `jarvisadmin`. FastAPI implementa el puente WebSocket hacia ese VNC; no hay puerto websockify abierto. El frontend usa noVNC. El Chrome normal de las tareas conserva `DISPLAY=:99` y su configuración actual. Los perfiles se bloquean con el mismo archivo `*.lock` que usa Selenium y con el coordinador de tareas. Hay una sola sesión visual por defecto, un solo visor por sesión y cierre tras 20 minutos sin actividad. El servicio cierra las sesiones visuales al detenerse y revisa procesos huérfanos registrados al iniciar.

La verificación abre Chrome temporalmente, lee la página inicial una vez y lo cierra. Solo declara `connected` si encuentra navegación autenticada; un resultado ambiguo se muestra como `unknown`. No publica, no extrae cookies y no guarda contraseñas. Cerrar el navegador visual no borra el perfil.

## Antes de desplegar

1. Hacer backup consistente de SQLite y guardar una copia del release actual. Verificar la ruta real con `systemctl cat instagram-bot`; en este VPS el proyecto se indica como `/home/jarvisadmin/apps/instagram-bot-linux`, mientras que la unidad de ejemplo del repositorio aún contiene `/opt/instagram-bot-linux`. No sobrescribir la unidad real.
2. Instalar con autorización administrativa `xvfb`, `xauth` y `x11vnc` en Ubuntu. Chrome ya debe estar disponible como `/usr/bin/google-chrome-stable`.
3. Usar un certificado público válido para `https://88.198.136.72`. Un dominio no es obligatorio: [Let's Encrypt emite certificados de IP de seis días](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability). Certbot 5.4+ puede solicitarlos con `--ip-address`, `--preferred-profile shortlived` y `--webroot`; la renovación automática y recarga de Nginx son indispensables. [Instrucciones oficiales](https://letsencrypt.org/2026/03/11/shorter-certs-certbot.html). Un certificado autofirmado no sirve como solución definitiva.
4. Revisar el bloque *real* de `nginx -T` antes de integrar [deploy/nginx-visual.example.conf](deploy/nginx-visual.example.conf). El ejemplo mantiene Basic Auth en todo el panel. Solo el WebSocket visual delega la autenticación al backend, que exige cookie administrativa corta, token CSRF en el subprotocolo y `Origin` HTTPS exacto. [Nginx requiere reenviar `Upgrade` y `Connection`](https://nginx.org/en/docs/http/websocket.html). No abrir 5901 ni los puertos de VNC por cuenta en el firewall.

## Configuración privada

Ejecutar desde el checkout Linux para generar el hash, sin poner la clave en la línea de comandos:

```bash
cd /home/jarvisadmin/apps/instagram-bot-linux
.venv/bin/python -c 'import getpass; from webapp.visual_auth import password_hash; print(password_hash(getpass.getpass("Clave visual: ")))'
```

Agregar al archivo privado `/etc/instagram-bot/instagram-bot.env`:

```ini
BOT_PUBLIC_ORIGIN=https://88.198.136.72
BOT_VISUAL_ADMIN_PASSWORD_HASH=pbkdf2_sha256:310000:SAL_GENERADA:HASH_GENERADO
BOT_VISUAL_MAX_SESSIONS=1
```

Copiar la línea completa generada, no los valores de ejemplo. El archivo de entorno debe ser legible solo por root y el usuario del servicio. `BOT_PUBLIC_ORIGIN` debe coincidir exactamente con el origen que muestra el navegador, sin barra final. La cookie es `Secure`, `HttpOnly`, `SameSite=Strict`, dura 30 minutos y se pierde al reiniciar el proceso; el administrador vuelve a ingresar la clave. El servidor debe correr como `jarvisadmin`, nunca root. El archivo XAUTHORITY generado se borra al cerrar la sesión. Ninguna contraseña de Instagram se guarda en SQLite.

## Diagnóstico del 401 móvil antes de cambiar Nginx

Con el fragmento compartido no se puede confirmar qué bloque `server` responde a Chrome móvil ni si el 401 procede de Basic Auth. Ejecutar el script de lectura `bash deploy/diagnose_mobile_access.sh 88.198.136.72` en el VPS y comparar sus líneas de estado con la petición fallida de Chrome móvil. No compartir el valor de `Authorization`, contraseñas ni cookies. Un 401 de Basic debe incluir `WWW-Authenticate: Basic ...`; el backend de diagnóstico usa `Bearer` en su endpoint específico. [Significado del encabezado](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/WWW-Authenticate). Revisar URL exacta, esquema, redirección, certificado, petición inicial y `/api/*` en ambos navegadores. La cache de credenciales Basic es independiente entre Chrome y Safari. El script nunca envía credenciales por HTTP.

Si el bloque HTTP tiene Basic Auth y redirección, verificar cuál responde primero. Tras obtener TLS válido, forzar la redirección HTTP→HTTPS en el bloque correcto, conservando Basic en HTTPS. No se debe cambiar Nginx sin revisar `nginx -T`, respaldar la configuración, probar `sudo nginx -t` y obtener aprobación para aplicarla.

## Uso

1. En **Cuentas**, pulsar **Agregar cuenta**, escribir nombre y perfil (por ejemplo `cuenta2`). El backend valida la ruta y crea el directorio solo si falta. Un perfil existente conserva sus archivos.
2. Pulsar **Iniciar sesión / verificar** en la tarjeta de la cuenta. Ingresar la clave de administración visual. Pulsar **Iniciar sesión**.
3. En el visor noVNC, ingresar a Instagram manualmente y completar cualquier verificación normal. Nunca introducir la clave de Instagram en el formulario de administración.
4. Pulsar **Cerrar navegador** al terminar. Luego **Verificar conexión** para obtener el estado. Si la verificación es ambigua, se muestra **No verificada**.
5. Si el WebSocket cae, pulsar **Reconectar visor**. Si Chrome o VNC fallaron, cerrar la sesión visual y volver a abrirla. Una cuenta en uso por una tarea rechaza el inicio visual.

## Despliegue controlado y vuelta atrás

Los siguientes comandos preparan el release después de subir esta rama al repositorio remoto. No se ejecutaron en producción:

```bash
cd /home/jarvisadmin/apps/instagram-bot-linux
git fetch origin feature/account-visual-login-mobile
git switch feature/account-visual-login-mobile
.venv/bin/pip install -r requirements-server.txt
cd frontend && npm ci && npm run build && cd ..
.venv/bin/python -m pytest -q
command -v Xvfb xauth x11vnc google-chrome-stable
sudo nginx -t
```

Tras revisar backups, configuración y pruebas en el VPS, los comandos de activación para una ventana aprobada son:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl restart instagram-bot
sudo systemctl status instagram-bot --no-pager
sudo journalctl -u instagram-bot -n 80 --no-pager
```

No ejecutar esos comandos hasta aprobar el cambio de infraestructura. La migración SQLite agrega `accounts.session_status`, `accounts.session_checked_at` y `admin_events` en el primer arranque; no altera los datos de perfiles. Para volver atrás: detener `instagram-bot`, restaurar el código y la copia de base correspondientes, y revertir solo el fragmento de Nginx aplicado. Los procesos visuales se cierran al detener el servicio. No reanudar automáticamente tareas interrumpidas.

## Validación supervisada pendiente

En el VPS: iniciar una cuenta de prueba sin tarea activa, confirmar que aparece solo en su visor, cerrar y verificar que el perfil se libera; intentar abrir la misma cuenta dos veces; comprobar Chrome móvil, Safari y Windows por HTTPS; comprobar que un WebSocket sin cookie/CSRF/Origin recibe rechazo; y confirmar que los puertos VNC siguen unidos a loopback. No ejecutar comentarios automatizados en esta prueba.
