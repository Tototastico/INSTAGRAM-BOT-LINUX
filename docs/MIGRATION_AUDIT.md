# Auditoría del Repositorio INSTAGRAM-BOT

**Fecha de auditoría:** 27 de Octubre de 2026  
**Rama de trabajo:** `feat/linux-vps-migration`  
**Commit base:** `e6f5f7732b20cbb1cd41f738309c25dca07ef8a0` (`origin/main`)

---

## 1. Arquitectura General y Flujo de Ejecución

El proyecto cuenta con dos modalidades de uso:
1. **Desktop/Legacy (`GUI.py`, `main.py`):**
   - Interfaz PyQt5 local (`GUI.py`) que escribe a `config.json` o ejecuta hilos en paralelo.
   - `main.py` lanza múltiples threads, uno por cada perfil listado en `config.json["perfil_chrome"]`.
2. **Web Local / Coordinador (`webapp/`):**
   - Backend FastAPI (`webapp/api.py`), base de datos SQLite (`webapp/db.py`), coordinador multi-hilo (`webapp/coordinator.py`), y adaptador Selenium (`webapp/runner.py` / `selenium_runner.py`).
   - Frontend React SPA con Vite (`frontend/`). Compilado a `frontend/dist/` servido por FastAPI en la raíz `/`.

---

## 2. Inspección de Componentes Críticos

### 2.1 Selenium y Detección de Chrome (`selenium_runner.py`, `webapp/chrome_binary.py`)
- **Estado actual de `webapp/chrome_binary.py`:**
  - Solo admite Windows mediante llamadas a `ctypes.WinDLL('version')` leyendo estructuras win32 `_FileVersionInfo`.
  - En Linux falla inmediatamente (`AttributeError: module 'ctypes' has no attribute 'WinDLL'`).
- **Estado actual de `selenium_runner.py`:**
  - Contiene una ruta fija cableada para Windows: `perfil_path = f"E:/tobias/INSTAGRAM-BOT/accounts/{nombre_cuenta}"`.
  - Opciones de Chrome incluyen `--no-sandbox` y `--disable-dev-shm-usage`.
  - Secuencia de navegación: `acceder_caja(url_post, nombre_cuenta)` navega al post, remueve foco activo, localiza `textarea[aria-label="Añade un comentario..."]`. Luego `comentar_en_post(comentario, driver, textarea)` tipea caracter a caracter y hace click en el botón "Publicar".
  - Ambos deben adaptarse para resolver rutas multiplataforma usando `Path` y variables de entorno, y en Linux permitir Xvfb con ejecución visual normal (no headless) con usuario no root.

### 2.2 Base de Datos SQLite (`webapp/db.py`, `data/bot.sqlite3`)
- **Modo:** WAL (`journal_mode = WAL`), `foreign_keys = ON`, `busy_timeout = 30000`.
- **Tablas reales identificadas:**
  - `meta`: `(key TEXT PRIMARY KEY, value TEXT NOT NULL)`
  - `accounts`: `(id INTEGER PRIMARY KEY, name TEXT NOT NULL, profile_arg TEXT NOT NULL, profile_path TEXT NOT NULL UNIQUE, archived INTEGER NOT NULL DEFAULT 0, attention_required INTEGER NOT NULL DEFAULT 0, attention_reason TEXT)`
  - `draws`: `(id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0)`
  - `assignments`: `(id INTEGER PRIMARY KEY, account_id INT REFERENCES accounts, draw_id INT REFERENCES draws, duration_minutes INT, comments_per_minute REAL, tag_count INT, extra_text TEXT, tags_json TEXT, archived INT, UNIQUE(account_id, draw_id))`
  - `tasks`: `(id INTEGER PRIMARY KEY, assignment_id INT REFERENCES assignments, status TEXT, elapsed_seconds REAL, attempts INT, clicked INT, confirmed INT, failures INT, last_error TEXT, created_at TEXT, updated_at TEXT)`
  - `events`: `(id INTEGER PRIMARY KEY, task_id INT REFERENCES tasks, kind TEXT, message TEXT, created_at TEXT)`
- **Índices:**
  - `idx_tasks_status` en `tasks(status)`
  - `idx_events_task` en `events(task_id, id DESC)`
- **Acoplamiento a Windows en la BD:**
  - Los registros de `accounts.profile_path` almacenan rutas completas en minúsculas tipo `e:\tobias\instagram-bot\accounts\cuenta1`. En Linux esto debe migrarse a `/var/lib/instagram-bot/accounts/cuenta1` respetando case-sensitivity.

### 2.3 Coordinador y Tareas (`webapp/coordinator.py`, `webapp/api.py`)
- **Exclusión de perfiles:** `self.active_profiles = {}` bloquea en memoria si un `profile_path` ya está activo. Si dos asignaciones usan el mismo perfil, la segunda espera en cola (`queued`).
- **Estados de tarea:** `queued`, `running`, `pausing`, `paused`, `cancelling`, `cancelled`, `completed`, `failed`, `interrupted`.
- **Cierre y recuperación:** `db.recover_interrupted()` marca tareas en ejecución/cola como `interrupted` al iniciar la app.
- **Falta en Linux:**
  - Bloqueo exclusivo de instancia única de proceso (`flock`).
  - Cierre ordenado mediante el lifespan de FastAPI para esperar la finalización segura de tareas activas (`driver.quit()`) antes de terminar.

### 2.4 Dependencias (`requirements.txt`, `requirements-web.txt`)
- `requirements.txt`: `PyQt5`, `selenium`, `undetected-chromedriver`.
- `requirements-web.txt`: `fastapi`, `uvicorn`, `pytest`, `httpx`.
- En el VPS Linux, `PyQt5` no debe ser instalado; se deben separar las dependencias de servidor (`requirements-server.txt`) y de desarrollo/escritorio (`requirements.txt`).

---

## 3. Plan de Acción por Fases

- **Fase 1:** Git seguro y baseline auditado (Completado).
- **Fase 2:** Compatibilidad multiplataforma de rutas y detección de Chrome (`webapp/chrome_binary.py`, `webapp/db.py`, `selenium_runner.py`).
- **Fase 3:** Coordinador, exclusión de instancia única (`flock` en Linux / `msvcrt` en Windows), y cierre ordenado FastAPI lifespan.
- **Fase 4:** Scripts de base de datos (`schema.sql`, `backup_sqlite.py`, `migrate_paths.py`, `validate_database.py`, `restore_sqlite.py`).
- **Fase 5:** Paquete de despliegue Ubuntu (`deploy/linux/`, systemd services, scripts de instalación y actualización).
- **Fase 6:** Tests unitarios y de integración multiplataforma.
- **Fase 7:** Documentación completa y verificación final.
