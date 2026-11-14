import re
import os
import inspect
from pathlib import Path
from .comment_field import COMMENT_CANDIDATE_SELECTOR, ready_comment_field
from .db import profile_path
from .settings import accounts_dir, ensure_private_dir

from comentarios import generar_comentario
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


class PendingCommentError(RuntimeError):
    pass


def parse_comment_count(value):
    text = value.strip().replace('\u00a0', ' ')
    if not re.fullmatch(r'\d+|\d{1,3}(?:[., ]\d{3})+', text):
        return None
    return int(re.sub(r'[., ]', '', text))


def compose_comment(tags, tag_count, extra_text):
    if not tags:
        raise ValueError('La asignacion necesita al menos una etiqueta')
    generated = generar_comentario(tags, tag_count)
    text = f'{generated} {extra_text.strip()}'.strip()
    return ''.join(char for char in text if ord(char) <= 0xFFFF)


class SeleniumRunner:
    def __init__(self):
        self.driver = None
        self.textarea = None
        self.event_sink = None
        self.open_error = None
        self.profile_lock = None
        self.diagnostic_sink = None
        self.stage_sink = None
        self.last_diagnostic_id = None

    def set_event_sink(self, sink):
        self.event_sink = sink

    def set_diagnostic_sink(self, sink):
        self.diagnostic_sink = sink

    def set_stage_sink(self, sink):
        self.stage_sink = sink

    def _mark_stage(self, stage):
        if self.stage_sink is not None:
            try:
                self.stage_sink(stage)
            except Exception:
                pass

    def _diagnose(self, stage, exc, driver, selector=''):
        if self.diagnostic_sink is not None:
            try:
                if not getattr(exc, 'bot_operation', None):
                    exc.bot_operation = stage
                self.last_diagnostic_id = self.diagnostic_sink(stage, exc, driver, selector)
            except Exception:
                pass  # Diagnostics must not hide the original Selenium failure.

    def _log(self, kind, message):
        if kind == 'selenium_error':
            self.open_error = message
        if self.event_sink is not None:
            try:
                self.event_sink(kind, message)
            except Exception:
                pass

    def open(self, url, profile_arg):
        from selenium_runner import acceder_caja

        if os.name == 'posix':
            import fcntl
            ensure_private_dir(accounts_dir())
            lock_path = accounts_dir() / (Path(profile_path(profile_arg)).name + '.lock')
            self.profile_lock = open(lock_path, 'a+b')
            lock_path.chmod(0o600)
            try:
                fcntl.flock(self.profile_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.profile_lock.close()
                self.profile_lock = None
                raise RuntimeError('El perfil Chrome ya esta en uso')

        self.open_error = None
        self.last_diagnostic_id = None
        kwargs = {}
        if self.event_sink is not None:
            kwargs['on_log'] = self._log
        if self.stage_sink is not None:
            kwargs['on_stage'] = self._mark_stage
        if self.diagnostic_sink is not None:
            kwargs['on_diagnostic'] = self._diagnose
        success, self.driver, self.textarea = acceder_caja(url, profile_arg, **kwargs)
        if not success:
            self._check_session()
            detail = f': {self.open_error}' if self.open_error else ''
            raise RuntimeError(f'No se pudo abrir la caja de comentarios; revisa la sesion o la interfaz{detail}')
        self._check_session()

    def read_comment_count(self):
        # Read the counter next to the comment icon without changing navigation or focus.
        selector = 'svg[aria-label="Comentar"], svg[aria-label="Comment"]'
        try:
            icons = self.driver.find_elements(By.CSS_SELECTOR, selector)
            for icon in icons:
                counters = icon.find_elements(
                    By.XPATH, './ancestor::span[1]/following-sibling::span[@role="button"][1]'
                )
                for counter in counters:
                    count = parse_comment_count(counter.text)
                    if count is not None:
                        return count
            return None
        except Exception as exc:
            self._diagnose('comment_count', exc, self.driver, selector)
            raise

    def post(self, comment):
        from selenium_runner import comentar_en_post

        self.last_diagnostic_id = None
        self._check_session()
        for attempt in range(3):
            try:
                pending = self.textarea.get_property('value')
                if pending is None:
                    pending = self.textarea.get_attribute('value')
                break
            except StaleElementReferenceException as exc:
                if attempt == 2:
                    self._diagnose('comment_box_refresh', exc, self.driver, '')
                    raise RuntimeError('El textarea cambio repetidamente antes de escribir; revisa la tarea') from exc
                self._log('selenium_retry', 'Textarea obsoleto antes de escribir; buscando el elemento actual')
                self._check_session()
                try:
                    self.textarea = WebDriverWait(
                        self.driver, 5, ignored_exceptions=(NoSuchElementException, StaleElementReferenceException)
                    ).until(ready_comment_field)
                except Exception as refresh_error:
                    self._diagnose('comment_box_refresh', refresh_error, self.driver, COMMENT_CANDIDATE_SELECTOR)
                    raise
            except Exception as exc:
                self._diagnose('comment_box_pending_check', exc, self.driver, COMMENT_CANDIDATE_SELECTOR)
                raise
        if pending and pending.strip():
            raise PendingCommentError('La caja de comentarios conserva texto; posible bloqueo o comentario pendiente')
        try:
            tag_name = getattr(self.textarea, 'tag_name', '').lower()
            if (tag_name and tag_name not in ('textarea', 'input') and
                    self.textarea.get_attribute('contenteditable') == 'true' and
                    (self.textarea.get_property('textContent') or '').strip()):
                raise PendingCommentError('El editor conserva texto; posible comentario pendiente')
        except PendingCommentError:
            raise
        except Exception as exc:
            self._diagnose('comment_box_pending_check', exc, self.driver, COMMENT_CANDIDATE_SELECTOR)
            raise
        kwargs = {}
        if self.stage_sink is not None:
            kwargs['on_stage'] = self._mark_stage
        if self.diagnostic_sink is not None:
            kwargs['on_diagnostic'] = self._diagnose
        if self.event_sink is not None and 'on_log' in inspect.signature(comentar_en_post).parameters:
            kwargs['on_log'] = self._log
        try:
            comentar_en_post(comment, self.driver, self.textarea, **kwargs)
        except Exception as exc:
            if getattr(exc, 'bot_operation', '') == 'publish_button.click':
                raise PendingCommentError(
                    'Resultado del clic en publicar incierto; revisar manualmente antes de continuar') from exc
            raise

    def _check_session(self):
        if self.driver is None:
            return
        try:
            url = (getattr(self.driver, 'current_url', '') or '').lower()
        except Exception as exc:
            self._diagnose('session_check', exc, self.driver)
            raise
        if '/accounts/login' in url:
            error = RuntimeError('Sesion vencida: inicia sesion manualmente en el perfil')
            self._diagnose('session_check', error, self.driver)
            raise error
        if '/challenge' in url or '/checkpoint' in url:
            error = RuntimeError('Instagram solicita una verificacion manual')
            self._diagnose('session_check', error, self.driver)
            raise error

    def close(self):
        try:
            if self.driver is not None:
                self.driver.quit()
                self.driver = None
        finally:
            if self.profile_lock is not None:
                self.profile_lock.close()
                self.profile_lock = None
