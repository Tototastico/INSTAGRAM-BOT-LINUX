"""Private, bounded Selenium failure evidence. Never stores page source or exception text."""
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from .db import now, row, rows
from .settings import debug_dir, diagnostic_retention_days, ensure_private_dir

COMMENT_SELECTOR = 'textarea[aria-label="Añade un comentario..."], textarea[aria-label="Add a comment..."]'


def safe_url(raw):
    try:
        parsed = urlsplit(raw or '')
        if parsed.scheme != 'https' or parsed.hostname not in ('instagram.com', 'www.instagram.com'):
            return '[sitio externo o URL no disponible]'
        path = parsed.path
        if re.fullmatch(r'/(p|reel)/[A-Za-z0-9_-]+/?', path):
            return f'https://{parsed.hostname}{path}'
        if path.startswith('/accounts/login'):
            return f'https://{parsed.hostname}/accounts/login/'
        if path.startswith(('/challenge', '/checkpoint')):
            return f'https://{parsed.hostname}/challenge/'
        return f'https://{parsed.hostname}/[ruta omitida]'
    except (ValueError, TypeError):
        return '[URL no disponible]'


def _safe_title(value, sensitive):
    if sensitive:
        return '[oculto por privacidad]'
    title = re.sub(r'https?://\S+|[\w.+-]+@[\w.-]+', '[oculto]', str(value or ''))
    return ''.join(char for char in title if char.isprintable())[:160]


def _probe(driver, selector):
    info = {'page_url': '', 'page_title': '', 'ready_state': 'desconocido',
            'browser_responding': 0, 'matching_elements': None,
            'visible_elements': None, 'dialog_count': None, 'login_fields': 0,
            'post_unavailable': False}
    if driver is None:
        return info
    try:
        current = safe_url(driver.current_url)
        sensitive = any(part in current.lower() for part in ('/accounts/login', '/challenge', '/checkpoint', '/direct/'))
        info['page_url'] = current
        info['ready_state'] = str(driver.execute_script('return document.readyState') or 'desconocido')[:30]
        info['browser_responding'] = 1
        info['login_fields'] = len(driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]'))
        sensitive = sensitive or bool(info['login_fields'])
        info['page_title'] = _safe_title(driver.title, sensitive)
        info['post_unavailable'] = bool(driver.execute_script('''
            const body = (document.body?.innerText || '').toLowerCase();
            return body.includes("sorry, this page isn't available") ||
                   body.includes('esta página no está disponible') ||
                   body.includes('esta pagina no esta disponible');
        '''))
        if selector:
            found = driver.find_elements(By.CSS_SELECTOR, selector)
            info['matching_elements'] = len(found)
            info['visible_elements'] = sum(1 for element in found if element.is_displayed() and element.is_enabled())
        info['dialog_count'] = len(driver.find_elements(By.CSS_SELECTOR, '[role="dialog"]'))
    except (WebDriverException, AttributeError, OSError, ValueError):
        pass
    return info


def _category(info, stage, exc):
    url = info['page_url'].lower()
    if not info['browser_responding']:
        return 'browser_unresponsive', 'Chrome no responde a los comandos de Selenium.'
    if info['login_fields'] or '/accounts/login' in url:
        return 'session', 'La pagina muestra un formulario de inicio de sesion.'
    if '/challenge' in url or '/checkpoint' in url:
        return 'verification', 'Instagram solicita una verificacion manual.'
    if not any(part in url for part in ('/p/', '/reel/')):
        return 'navigation', 'La navegacion no termino en la publicacion esperada.'
    if info['post_unavailable']:
        return 'post_unavailable', 'Instagram indica que la publicacion no esta disponible.'
    if info['ready_state'] != 'complete':
        return 'page_loading', 'El documento aun no termino de cargar.'
    if info['matching_elements'] == 0:
        return 'selector_missing', 'No se encontro la caja con el selector actual; revisa idioma o interfaz.'
    if info['matching_elements'] and info['visible_elements'] == 0:
        return 'not_interactable', 'La caja existe, pero no esta visible o habilitada.'
    if type(exc).__name__ == 'ElementNotInteractableException':
        return 'not_interactable', 'Selenium encontro el elemento, pero no pudo interactuar con el.'
    if info['dialog_count']:
        return 'overlay', 'Hay un dialogo visible que puede impedir la interaccion.'
    return 'interaction', f'Fallo de Selenium durante {stage}.'


class DiagnosticStore:
    def __init__(self, db):
        self.db = db

    def prune(self):
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=diagnostic_retention_days())
        cutoff = cutoff_time.isoformat(timespec='seconds')
        with self.db.connect() as con:
            expired = rows(con, 'SELECT screenshot_file FROM task_diagnostics WHERE created_at<?', (cutoff,))
            con.execute('DELETE FROM task_diagnostics WHERE created_at<?', (cutoff,))
            active = {item['screenshot_file'] for item in rows(
                con, 'SELECT screenshot_file FROM task_diagnostics WHERE screenshot_file IS NOT NULL')}
        root = debug_dir()
        for item in expired:
            filename = item['screenshot_file']
            if filename and re.fullmatch(r'[0-9a-f]{32}\.png', filename):
                (root / filename).unlink(missing_ok=True)
        if root.is_dir():
            for path in root.glob('*.png'):
                if path.name not in active and re.fullmatch(r'[0-9a-f]{32}\.png', path.name):
                    try:
                        if path.stat().st_mtime < cutoff_time.timestamp():
                            path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def record(self, task_id, account_id, stage, exc, driver=None, selector=COMMENT_SELECTOR):
        diagnostic_id = uuid.uuid4().hex
        info = _probe(driver, selector)
        category, summary = _category(info, stage, exc)
        error_type = type(exc).__name__[:80]
        screenshot_file = None
        page = info['page_url'].lower()
        safe_page = any(part in page for part in ('instagram.com/p/', 'instagram.com/reel/'))
        if isinstance(exc, WebDriverException) and safe_page and not info['login_fields'] and info['browser_responding']:
            root = ensure_private_dir(debug_dir())
            target = root / f'{diagnostic_id}.png'
            try:
                if driver.save_screenshot(str(target)) and target.is_file():
                    if os.name == 'posix':
                        target.chmod(0o600)
                    screenshot_file = target.name
            except (WebDriverException, OSError, AttributeError):
                pass
            if screenshot_file is None:
                target.unlink(missing_ok=True)
        with self.db.connect() as con:
            con.execute('''INSERT INTO task_diagnostics
                (id,task_id,account_id,created_at,stage,error_type,category,summary,
                 page_url,page_title,ready_state,browser_responding,selector,
                 matching_elements,visible_elements,dialog_count,screenshot_file)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (diagnostic_id, task_id, account_id, now(), stage[:80], error_type,
                 category, summary, info['page_url'], info['page_title'], info['ready_state'],
                 info['browser_responding'], selector[:240], info['matching_elements'],
                 info['visible_elements'], info['dialog_count'], screenshot_file))
        self.prune()
        return diagnostic_id

    def for_task(self, task_id):
        with self.db.connect() as con:
            return rows(con, '''SELECT id,created_at,stage,error_type,category,summary,page_url,
                page_title,ready_state,browser_responding,selector,matching_elements,
                visible_elements,dialog_count,(screenshot_file IS NOT NULL) has_screenshot
                FROM task_diagnostics WHERE task_id=? ORDER BY created_at DESC LIMIT 20''', (task_id,))

    def screenshot(self, task_id, diagnostic_id):
        with self.db.connect() as con:
            item = row(con, 'SELECT screenshot_file FROM task_diagnostics WHERE task_id=? AND id=?',
                       (task_id, diagnostic_id))
        if not item or not item['screenshot_file']:
            return None
        filename = item['screenshot_file']
        if not re.fullmatch(r'[0-9a-f]{32}\.png', filename):
            return None
        path = debug_dir() / filename
        return path if path.is_file() else None
