# Compatibilidad Multiplataforma (Windows y Linux)

Este repositorio mantiene paridad operativa para ambos entornos sin comprometer el funcionamiento preexistente en Windows.

---

## 1. Detección y Normalización de Rutas
- En **Windows**, las rutas se siguen resolviendo en minúsculas en `accounts/<cuenta>`, preservando las asignaciones históricas existentes en `bot.sqlite3`.
- En **Linux**, `webapp/paths.py` respeta la distinción de mayúsculas y minúsculas (case sensitivity) del sistema de archivos ext4.
- `resolve_profile_path("cuenta1")` y `resolve_profile_path("accounts/cuenta1")` resuelven al mismo directorio físico tanto en Windows como en Linux sin duplicación.

---

## 2. Detección de Google Chrome
- En **Windows**, `webapp/chrome_binary.py` continúa usando la API oficial de Windows (`ctypes.WinDLL('version')`) y `uc.find_chrome_executable()`.
- En **Linux**, ejecuta `google-chrome-stable --version` vía `subprocess.run` (sin shell, con control de inyecciones) extrayendo la versión principal numérica y pasando `version_main` al driver.

---

## 3. Bloqueo de Instancia Única
- En **Linux**, `webapp/instance_lock.py` utiliza `fcntl.flock(fileno, LOCK_EX | LOCK_NB)`.
- En **Windows**, utiliza `msvcrt.locking` sobre el primer byte del archivo.
- En ambos sistemas, previene aperturas simultáneas de múltiples servidores Uvicorn sobre la misma base y perfiles.

---

## 4. Ejecución Gráfica y de Escritorio
- Las herramientas de escritorio existentes (`GUI.py`, `main.py`) que utilizan `PyQt5` siguen funcionando en Windows.
- El servidor VPS Linux prescinde de `PyQt5` gracias a `requirements-server.txt`, evitando fallos de compilación de Qt en entornos sin pantalla física.
