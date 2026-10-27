# Base de Datos SQLite — INSTAGRAM-BOT

Este directorio contiene el esquema formal, herramientas de migración, respaldo y validación para entornos Windows y Linux.

## Estructura

```text
database/
├── schema.sql                     # Esquema SQL unificado DDL
├── migrations/                    # Migraciones versionadas (si aplican)
└── scripts/
    ├── init_database.py           # Inicialización limpia desde schema.sql
    ├── backup_sqlite.py           # Respaldo consistente con SQLite Online Backup API
    ├── validate_database.py       # Comprobación de integridad, FKs y estructura
    ├── migrate_paths.py           # Migración transaccional de rutas con preview
    └── restore_sqlite.py          # Restauración segura desde backup con verificación
```

## Guía de Uso

### 1. Inicialización de Base Nueva
```bash
python database/scripts/init_database.py --db /var/lib/instagram-bot/data/bot.sqlite3
```

### 2. Respaldo de Base Existente (WAL Compatible)
```bash
python database/scripts/backup_sqlite.py --db /var/lib/instagram-bot/data/bot.sqlite3 --out /var/lib/instagram-bot/backups
```

### 3. Validación de Integridad
```bash
python database/scripts/validate_database.py --db /var/lib/instagram-bot/data/bot.sqlite3
```

### 4. Migración de Rutas Windows -> Linux
**Paso 1: Vista Previa (Dry Run)**
```bash
python database/scripts/migrate_paths.py --db /var/lib/instagram-bot/data/bot.sqlite3 --accounts-dir /var/lib/instagram-bot/accounts
```

**Paso 2: Aplicación Definitiva (Crea backup previo automáticamente)**
```bash
python database/scripts/migrate_paths.py --db /var/lib/instagram-bot/data/bot.sqlite3 --accounts-dir /var/lib/instagram-bot/accounts --apply
```

### 5. Restauración desde un Respaldo
```bash
python database/scripts/restore_sqlite.py --backup /var/lib/instagram-bot/backups/bot_20261027_120000.sqlite3 --target /var/lib/instagram-bot/data/bot.sqlite3
```
