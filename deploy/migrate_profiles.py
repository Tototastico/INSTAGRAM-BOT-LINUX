"""Preview or migrate account paths after an explicitly restored SQLite backup."""
import argparse
import sqlite3

from webapp.db import profile_path
from webapp.settings import db_path

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true', help='Commit the displayed path changes')
args = parser.parse_args()

with sqlite3.connect(db_path()) as con:
    con.row_factory = sqlite3.Row
    accounts = list(con.execute('SELECT id,profile_arg,profile_path FROM accounts ORDER BY id'))
    updates = [(item['id'], item['profile_path'], profile_path(item['profile_arg'])) for item in accounts]
    paths = [target for _, _, target in updates]
    if len(paths) != len(set(paths)):
        raise SystemExit('Colision de rutas de perfil; corrige profile_arg antes de aplicar')
    for item_id, old, new in updates:
        if old != new:
            print(f'{item_id}: {old} -> {new}')
    if args.apply:
        # Two phases permit swaps while preserving the UNIQUE constraint.
        for item_id, old, new in updates:
            if old != new:
                con.execute('UPDATE accounts SET profile_path=? WHERE id=?', (f'__migration_{item_id}__', item_id))
        for item_id, old, new in updates:
            if old != new:
                con.execute('UPDATE accounts SET profile_path=? WHERE id=?', (new, item_id))
        con.commit()
        print('Rutas actualizadas')
    else:
        print('Vista previa; ejecuta --apply despues de respaldar')
