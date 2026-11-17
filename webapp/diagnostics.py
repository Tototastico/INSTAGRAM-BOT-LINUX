"""Private Selenium failure evidence with redacted exception messages."""
import os
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from .comment_field import COMMENT_CANDIDATE_SELECTOR, comment_candidates
from .db import now, row, rows
from .settings import debug_dir, diagnostic_retention_days, ensure_private_dir

COMMENT_SELECTOR = COMMENT_CANDIDATE_SELECTOR


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


def safe_exception_message(exc):
    """Keep Selenium's technical message and stack trace while hiding secret values."""
    message = str(exc)
    message = re.sub(r'https?://[^\s<>"\']+', lambda match: safe_url(match.group()), message)
    message = re.sub(r'(?im)^\s*(?:cookie|set-cookie|authorization):.*$', '[cabecera oculta]', message)
    message = re.sub(r'(?i)\bBearer\s+[^\s,;]+', 'Bearer [oculto]', message)
    message = re.sub(
        r'(?i)\b(password|passwd|token|access_token|refresh_token|cookie|sessionid|secret|csrf|xsrf)\b(\s*[:=]\s*)([^\s,;]+)',
        r'\1\2[oculto]', message)
    message = re.sub(r'\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[token oculto]', message)
    return ''.join(char for char in message if char.isprintable() or char in '\n\t')


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
        if selector == COMMENT_SELECTOR:
            found = comment_candidates(driver)
            info['matching_elements'] = len(found)
            info['visible_elements'] = sum(1 for _, state in found if state['visible'] and state['enabled'])
        elif selector:
            found = driver.find_elements(By.CSS_SELECTOR, selector)
            info['matching_elements'] = len(found)
            info['visible_elements'] = sum(1 for element in found if element.is_displayed() and element.is_enabled())
        info['dialog_count'] = len(driver.find_elements(By.CSS_SELECTOR, '[role="dialog"]'))
    except (WebDriverException, AttributeError, OSError, ValueError):
        pass
    return info


def _category(info, stage, exc, operation):
    url = info['page_url'].lower()
    if type(exc).__name__ == 'ProfilePreferencesTooLarge':
        return 'profile_preferences_oversized', 'El archivo Preferences del perfil es demasiado grande para iniciar Chrome sin agotar la memoria.'
    if stage == 'chrome_start':
        return 'browser_start_failed', 'Chrome no completo el arranque; revisar memoria, limites del servicio y procesos del perfil.'
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
    if operation == 'driver.get':
        return 'navigation', 'Fallo la navegacion a la publicacion.'
    if operation in ('crear_driver', 'document.readyState'):
        return 'browser_state', 'Fallo la preparacion o consulta del navegador.'
    if type(exc).__name__ == 'PendingCommentError':
        return 'pending_comment', 'El editor conserva texto; la tarea se pauso para revision manual.'
    if type(exc).__name__ == 'SessionUnavailableError':
        return 'session', 'La sesion requiere revision manual.'
    if stage == 'publish_button_lookup':
        state = getattr(exc, 'bot_control_state', {}) or {}
        if state.get('stale_references') and not state.get('button_matches'):
            return 'stale_reference', 'El DOM reemplazo un elemento durante la busqueda del control.'
        if not state.get('editor_matches'):
            return 'editor_changed', 'No se pudo confirmar el editor activo con el comentario esperado.'
        if state.get('ambiguous'):
            return 'ambiguous_control', 'Hay mas de un control de publicar junto al editor.'
        if not state.get('button_matches'):
            return 'selector_missing', 'No se encontro Post/Publicar junto al editor activo.'
        if not state.get('visible'):
            return 'not_visible', 'El control de publicar existe, pero no esta visible.'
        if not state.get('enabled'):
            return 'not_interactable', 'El control de publicar esta deshabilitado.'
        return 'interaction', 'La espera del control de publicar termino sin un control estable.'
    if info['matching_elements'] == 0:
        return 'selector_missing', 'No se encontro la caja con el selector actual; revisa idioma o interfaz.'
    if info['matching_elements'] and info['visible_elements'] == 0:
        return 'not_interactable', 'La caja existe, pero no esta visible o habilitada.'
    if operation in ('find_elements', 'comment_field.lookup', 'publish_button.lookup'):
        return 'element_lookup', 'Fallo la busqueda o espera del elemento.'
    if operation.endswith(('is_displayed', 'is_enabled', 'confirm')):
        return 'visibility', 'Fallo la comprobacion de visibilidad o estado editable.'
    if type(exc).__name__ == 'ElementNotInteractableException':
        return 'not_interactable', 'Selenium encontro el elemento, pero no pudo interactuar con el.'
    if info['dialog_count']:
        return 'overlay', 'Hay un dialogo visible que puede impedir la interaccion.'
    return 'interaction', f'Fallo de Selenium durante {stage}, operacion {operation or "desconocida"}.'


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
        operation = str(getattr(exc, 'bot_operation', '') or '')[:100]
        condition = str(getattr(exc, 'bot_condition', '') or '')[:240]
        category, summary = _category(info, stage, exc, operation)
        error_type = type(exc).__name__[:80]
        error_message = (safe_exception_message(exc) if isinstance(exc, WebDriverException)
                         else str(getattr(exc, 'bot_safe_message', ''))[:600])
        control_state = getattr(exc, 'bot_control_state', {}) or {}
        allowed = ('editor_matches', 'button_matches', 'visible', 'enabled',
                   'stale_references', 'ambiguous', 'scope',
                   'mem_available_mb', 'swap_free_mb', 'tmp_free_mb', 'shm_free_mb',
                   'cgroup_memory_mb', 'cgroup_limit_mb', 'cgroup_oom_kills',
                   'cgroup_pids', 'cgroup_pids_limit', 'profile_chrome_running')
        control_state = json.dumps({key: control_state[key] for key in allowed if key in control_state})
        control_structure = str(getattr(exc, 'bot_control_structure', '') or '')[:600]
        screenshot_file = None
        page = info['page_url'].lower()
        safe_page = any(part in page for part in ('instagram.com/p/', 'instagram.com/reel/'))
        evidence_error = isinstance(exc, WebDriverException) or type(exc).__name__ in (
            'PendingCommentError', 'SessionUnavailableError')
        if evidence_error and safe_page and not info['login_fields'] and info['browser_responding']:
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
                 matching_elements,visible_elements,dialog_count,screenshot_file,
                 operation,condition,error_message,control_state,control_structure)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (diagnostic_id, task_id, account_id, now(), stage[:80], error_type,
                 category, summary, info['page_url'], info['page_title'], info['ready_state'],
                 info['browser_responding'], selector[:240], info['matching_elements'],
                 info['visible_elements'], info['dialog_count'], screenshot_file,
                 operation, condition, error_message, control_state, control_structure))
        self.prune()
        return diagnostic_id

    def for_task(self, task_id):
        with self.db.connect() as con:
            return rows(con, '''SELECT id,created_at,stage,error_type,category,summary,page_url,
                page_title,ready_state,browser_responding,selector,matching_elements,
                visible_elements,dialog_count,operation,condition,error_message,
                control_state,control_structure,
                (screenshot_file IS NOT NULL) has_screenshot
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
