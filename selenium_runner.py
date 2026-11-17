import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
import time
import random
import threading
from selenium.common.exceptions import (ElementNotInteractableException,
                                        StaleElementReferenceException, NoSuchElementException,
                                        WebDriverException)
from webapp.chrome_binary import chrome_binary_and_major
from webapp.comment_field import (COMMENT_CANDIDATE_SELECTOR, confirm_comment_field,
                                  ready_comment_field)
from webapp.publish_button import (PUBLISH_CONTROL_SELECTOR, PublishButtonProbe,
                                   safe_button_state)
from webapp.db import profile_path
from webapp.settings import ensure_private_dir, headless, validate_visual_environment
from webapp.startup_health import startup_snapshot
from pathlib import Path

COMMENT_TEXTAREA_SELECTOR = COMMENT_CANDIDATE_SELECTOR
_chrome_start_lock = threading.Lock()
PREFERENCES_MAX_MB = 64


class ProfilePreferencesTooLarge(RuntimeError):
    """Stop before undetected-chromedriver loads an oversized profile JSON."""


def _check_preferences_size(profile):
    preferences = Path(profile) / 'Default' / 'Preferences'
    try:
        size = preferences.stat().st_size
    except FileNotFoundError:
        return
    if size > PREFERENCES_MAX_MB * 1024 * 1024:
        error = ProfilePreferencesTooLarge(
            f'Preferences del perfil ocupa {size // (1024 * 1024)} MB; '
            f'limite preventivo {PREFERENCES_MAX_MB} MB. No se abrio Chrome ni se modifico el perfil.')
        error.bot_safe_message = str(error)
        raise error


def _operation_error(exc, operation, condition=''):
    if not getattr(exc, 'bot_operation', None):
        exc.bot_operation = operation
    exc.bot_condition = condition
    return exc


def report(message, on_log=None, kind='selenium_info'):
    print(message)
    if on_log is not None:
        try:
            on_log(kind, message)
        except Exception:
            pass

def crear_driver(nombre_cuenta):
    chrome_executable, chrome_major = chrome_binary_and_major()
    options = uc.ChromeOptions()
    perfil_path = profile_path(nombre_cuenta)
    ensure_private_dir(Path(perfil_path))
    options.add_argument(f"--user-data-dir={perfil_path}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1365,900")
    if headless():
        options.add_argument('--headless=new')
    else:
        validate_visual_environment()
    options.add_argument("--disable-dev-shm-usage")

    # uc.Chrome patches a shared driver binary before launching Chrome.
    # Keep concurrent accounts from modifying it during another startup.
    with _chrome_start_lock:
        _check_preferences_size(perfil_path)
        try:
            driver = uc.Chrome(options=options, browser_executable_path=chrome_executable,
                               version_main=chrome_major, use_subprocess=False)
        except WebDriverException as exc:
            try:
                exc.bot_control_state = startup_snapshot(perfil_path)
            except Exception:
                exc.bot_control_state = {}
            raise
    return driver

def acceder_caja(url_post, nombre_cuenta, on_log=None, on_stage=None, on_diagnostic=None):
    print(f"[+] Iniciando sesión con la cuenta: {nombre_cuenta}")
    driver = None
    stage = 'chrome_start'
    operation = 'crear_driver'
    condition = ''
    try:
        if on_stage:
            on_stage(stage)
        driver = crear_driver(nombre_cuenta)
        stage = 'navigation'
        operation = 'driver.get'
        if on_stage:
            on_stage(stage)
        driver.get(url_post)
        stage = 'page_ready'
        operation = 'document.readyState'
        condition = 'document.readyState == complete'
        if on_stage:
            on_stage(stage)
        WebDriverWait(driver, 15).until(
            lambda current: current.execute_script('return document.readyState') == 'complete')
        stage = 'comment_box_lookup'
        operation = 'find_elements'
        condition = 'editor de comentario visible y habilitado'
        if on_stage:
            on_stage(stage)
        wait = WebDriverWait(driver, 15)
        for intento in range(3):
            try:
                textarea = wait.until(ready_comment_field)
                operation = 'comment_field.click'
                condition = 'editor reconocido visible y habilitado'
                textarea.click()
                operation = 'comment_field.focus_check'
                condition = 'document.activeElement == editor de comentario'
                if not confirm_comment_field(textarea) or not driver.execute_script(
                        'return document.activeElement === arguments[0]', textarea):
                    raise ElementNotInteractableException('El editor de comentario no quedo enfocado')
                if on_stage:
                    on_stage('comment_box_ready')
                return True, driver, textarea
            except (StaleElementReferenceException, NoSuchElementException) as exc:
                if intento == 2:
                    raise
                report(f"[!] Reintentando encontrar editor (intento {intento + 1}/3): {type(exc).__name__}",
                       on_log, 'selenium_retry')
                time.sleep(2)

    except Exception as e:
        _operation_error(e, operation, condition)
        if on_diagnostic:
            on_diagnostic(stage, e, driver, COMMENT_TEXTAREA_SELECTOR if stage == 'comment_box_lookup' else '')
        detail = f': {e}' if isinstance(e, ProfilePreferencesTooLarge) else ''
        report(f"[!] Error al abrir la caja de comentarios durante {stage}, operacion {operation}: {type(e).__name__}{detail}",
               on_log, 'selenium_error')
        return False, driver, None


def comentar_en_post(comentario, driver, textarea, on_stage=None, on_diagnostic=None, on_log=None):
    stage = 'comment_typing'
    operation = 'comment_field.confirm'
    condition = 'editor de comentario visible y habilitado'
    probe = None
    try:
        if on_stage:
            on_stage(stage)
        if not confirm_comment_field(textarea) or not driver.execute_script(
                'return document.activeElement === arguments[0]', textarea):
            raise ElementNotInteractableException('No se confirma el foco del editor de comentario')
        wait = WebDriverWait(driver, 5)
        for letra in comentario:
            operation = 'comment_field.send_keys'
            textarea.send_keys(letra)
            time.sleep(random.uniform(0.05, 0.15))

        time.sleep(random.uniform(1, 2))
        stage = 'publish_button_lookup'
        operation = 'publish_button.lookup'
        condition = 'un unico boton Post/Publicar visible y habilitado junto al editor activo con el texto esperado'
        if on_stage:
            on_stage(stage)
        probe = PublishButtonProbe(comentario)
        _, publicar_btn = wait.until(probe)
        if on_log:
            on_log('publish_button_state', str(safe_button_state(probe)))
        operation = 'publish_button.scroll'
        driver.execute_script("arguments[0].scrollIntoView(true);", publicar_btn)
        time.sleep(0.5)
        operation = 'publish_button.recheck'
        current = probe(driver)
        if not current:
            raise ElementNotInteractableException('El control de publicar cambio antes del clic')
        _, publicar_btn = current
        if on_log:
            on_log('publish_button_state', str(safe_button_state(probe)))
        stage = 'publish_click'
        operation = 'publish_button.click'
        if on_stage:
            on_stage(stage)
        driver.execute_script("arguments[0].click();", publicar_btn)
        print('[+] Clic en publicar ejecutado; resultado aun no verificado.')
    except Exception as exc:
        _operation_error(exc, operation, condition)
        if probe is not None:
            exc.bot_control_state = safe_button_state(probe)
            exc.bot_control_structure = probe.structure
        if on_diagnostic:
            selector = PUBLISH_CONTROL_SELECTOR if stage in ('publish_button_lookup', 'publish_click') else ''
            on_diagnostic(stage, exc, driver, selector)
        raise
