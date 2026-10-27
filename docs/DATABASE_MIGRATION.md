# Guía de Migración de Base de Datos SQLite

Esta guía explica cómo transferir y migrar la base de datos de producción desde Windows hacia Linux sin pérdida de datos ni inconsistencias.

---

## 1. Paso 1 — Respaldo en la máquina Windows
Antes de transferir, genera un respaldo consistente con la SQLite Online Backup API:

```bash
# En Windows:
python database/scripts/backup_sqlite.py --db data/bot.sqlite3 --out data/backups
```

---

## 2. Paso 2 — Transferencia de la Base al VPS
Transfiere la copia de seguridad al VPS vía SCP/SFTP:

```bash
scp data/backups/bot_*.sqlite3 usuario@vps:/tmp/bot_migracion.sqlite3
```

En el VPS, restaura la base en la ruta persistente de producción:
```bash
sudo -u instagram-bot /opt/instagram-bot/venv/bin/python /opt/instagram-bot/current/database/scripts/restore_sqlite.py \
    --backup /tmp/bot_migracion.sqlite3 \
    --target /var/lib/instagram-bot/data/bot.sqlite3
```

---

## 3. Paso 3 — Vista Previa de la Migración de Rutas (Dry-Run)
Las cuentas importadas en Windows tienen rutas absolutas tipo `e:\tobias\instagram-bot\accounts\cuenta1`.
Ejecuta la vista previa para verificar cómo se convertirán:

```bash
sudo -u instagram-bot /opt/instagram-bot/venv/bin/python /opt/instagram-bot/current/database/scripts/migrate_paths.py \
    --db /var/lib/instagram-bot/data/bot.sqlite3 \
    --accounts-dir /var/lib/instagram-bot/accounts
```

El script mostrará:
- Total de cuentas analizadas.
- Cuántas cambiarán.
- Comparación antes/después para cada perfil.
- Detección de colisiones si dos perfiles apuntaran al mismo destino.

---

## 4. Paso 4 — Aplicación Definitiva de la Migración
Aplica los cambios definitivamente usando el flag `--apply`:

```bash
sudo -u instagram-bot /opt/instagram-bot/venv/bin/python /opt/instagram-bot/current/database/scripts/migrate_paths.py \
    --db /var/lib/instagram-bot/data/bot.sqlite3 \
    --accounts-dir /var/lib/instagram-bot/accounts \
    --apply
```

> **Nota de Seguridad:** El script genera automáticamente un respaldo atómico previo antes de aplicar cualquier cambio.

---

## 5. Paso 5 — Validación de Integridad
Verifica que la base de datos sea 100% válida y consistente:

```bash
sudo -u instagram-bot /opt/instagram-bot/venv/bin/python /opt/instagram-bot/current/database/scripts/validate_database.py \
    --db /var/lib/instagram-bot/data/bot.sqlite3
```
Resultado esperado:
```text
=== REPORTE DE VALIDACIÓN SQLITE ===
Integrity check: OK
Quick check:     OK
Violaciones FK:  0
Tablas faltantes:[]
Resultado final: [VALIDA]
```
