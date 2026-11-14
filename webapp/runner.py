import re
import os
from pathlib import Path
from .db import profile_path
from .settings import accounts_dir, ensure_private_dir

from comentarios import generar_comentario
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
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

    def set_event_sink(self, sink):
        self.event_sink = sink

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
        if self.event_sink is None:
            success, self.driver, self.textarea = acceder_caja(url, profile_arg)
        else:
            success, self.driver, self.textarea = acceder_caja(url, profile_arg, on_log=self._log)
        if not success:
            self._check_session()
            detail = f': {self.open_error}' if self.open_error else ''
            raise RuntimeError(f'No se pudo abrir la caja de comentarios; revisa la sesion o la interfaz{detail}')
        self._check_session()

    def read_comment_count(self):
        # Read the counter next to the comment icon without changing navigation or focus.
        icons = self.driver.find_elements(By.CSS_SELECTOR, 'svg[aria-label="Comentar"], svg[aria-label="Comment"]')
        for icon in icons:
            counters = icon.find_elements(
                By.XPATH, './ancestor::span[1]/following-sibling::span[@role="button"][1]'
            )
            for counter in counters:
                count = parse_comment_count(counter.text)
                if count is not None:
                    return count
        return None

    def post(self, comment):
        from selenium_runner import comentar_en_post

        self._check_session()
        for attempt in range(3):
            try:
                pending = self.textarea.get_property('value')
                if pending is None:
                    pending = self.textarea.get_attribute('value')
                break
            except StaleElementReferenceException as exc:
                if attempt == 2:
                    raise RuntimeError('El textarea cambio repetidamente antes de escribir; revisa la tarea') from exc
                from selenium_runner import COMMENT_TEXTAREA_SELECTOR
                self._log('selenium_retry', 'Textarea obsoleto antes de escribir; buscando el elemento actual')
                self._check_session()
                self.textarea = WebDriverWait(
                    self.driver, 5, ignored_exceptions=(NoSuchElementException, StaleElementReferenceException)
                ).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, COMMENT_TEXTAREA_SELECTOR))
                )
        if pending and pending.strip():
            raise PendingCommentError('La caja de comentarios conserva texto; posible bloqueo o comentario pendiente')
        comentar_en_post(comment, self.driver, self.textarea)

    def _check_session(self):
        if self.driver is None:
            return
        url = (getattr(self.driver, 'current_url', '') or '').lower()
        if '/accounts/login' in url:
            raise RuntimeError('Sesion vencida: inicia sesion manualmente en el perfil')
        if '/challenge' in url or '/checkpoint' in url:
            raise RuntimeError('Instagram solicita una verificacion manual')

    def close(self):
        try:
            if self.driver is not None:
                self.driver.quit()
                self.driver = None
        finally:
            if self.profile_lock is not None:
                self.profile_lock.close()
                self.profile_lock = None
