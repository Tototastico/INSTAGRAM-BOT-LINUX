# Testing y Validación Automatizada

---

## 1. Ejecución de la Suite de Tests

Para ejecutar las pruebas en Windows o en Linux VPS:

```bash
# En Windows:
python -m pytest tests -v

# En Linux VPS:
/opt/instagram-bot/venv/bin/pytest tests -v
```

---

## 2. Cobertura de Tests
La suite automatizada incluye:
- `tests/test_chrome_version.py`: Detección y validación de Chrome.
- `tests/test_webapp.py`: Operaciones CRUD de asignaciones, cuentas y sorteos; exclusión de perfiles; tareas pausadas por detección de retos o comentarios pendientes.
- `tests/test_migration_and_platform.py`:
  - Normalización multiplataforma de rutas (`resolve_profile_path`).
  - Bloqueo de proceso único (`SingleInstanceLock`).
  - Inicialización limpia de SQLite (`init_database`).
  - Respaldo Online atómico (`backup_database`).
  - Validación de integridad y claves foráneas (`validate_database`).
  - Migración idempotente de rutas Windows a Linux (`migrate_account_paths`).
  - Restauración desde copias de seguridad (`restore_database`).
