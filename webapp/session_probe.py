"""Read-only, conservative Instagram authentication observations."""
import re
from urllib.parse import urlsplit

from selenium.webdriver.common.by import By


def normalize_user(value):
    return (value or '').strip().lstrip('@').casefold()


def probe(driver, expected=''):
    """Unknown is deliberately distinct from signed out; never infer auth from cookies."""
    try:
        url = (driver.current_url or '').lower().split('?', 1)[0]
        if '/challenge/' in url or '/checkpoint/' in url:
            return 'verification_required', '', 'Instagram solicita verificacion manual'
        if '/accounts/login' in url:
            return 'session_expired', '', 'Instagram redirigio al inicio de sesion'
        if any((getattr(element, 'tag_name', '').lower() == 'input' and
                (element.get_attribute('type') == 'password' or element.get_attribute('name') == 'username') and
                element.is_displayed()) for element in driver.find_elements(
                    By.CSS_SELECTOR, 'input[type="password"], input[name="username"]')):
            return 'not_signed_in', '', 'Formulario de inicio de sesion visible'
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href]')
        detected = ''
        for link in links:
            href = link.get_attribute('href') or ''
            path = urlsplit(href).path.strip('/')
            if not path or '/' in path or path in ('explore', 'reels', 'direct', 'accounts'):
                continue
            label = (link.get_attribute('aria-label') or '').casefold()
            icon = link.find_elements(By.CSS_SELECTOR, 'svg[aria-label="Profile"], svg[aria-label="Perfil"]')
            if label in ('profile', 'perfil') or icon:
                detected = path
                break
        if detected:
            if expected and re.fullmatch(r'@?[A-Za-z0-9._]+', expected.strip()) and normalize_user(detected) != normalize_user(expected):
                return 'wrong_account', detected, 'El usuario del perfil no coincide con la cuenta registrada'
            return 'connected', detected, 'Perfil autenticado identificado'
        # The login prompt can appear over a post without changing the URL.
        if any(getattr(element, 'tag_name', '').lower() in ('a', 'button') and element.is_displayed()
               for element in driver.find_elements(
                   By.CSS_SELECTOR, 'a[href*="/accounts/login/"], button[data-testid="login-button"]')):
            return 'not_signed_in', '', 'La publicacion solicita iniciar sesion'
        if any('log in to like or comment' in getattr(element, 'text', '').casefold() or
               'inicia sesión para indicar que te gusta o comentar' in getattr(element, 'text', '').casefold()
               for element in driver.find_elements(By.XPATH,
                   "//*[contains(text(),'Log in to like or comment') or contains(text(),'Inicia sesión para indicar que te gusta o comentar')]")):
            return 'not_signed_in', '', 'Instagram muestra un bloqueo de inicio de sesion sobre la publicacion'
        if driver.find_elements(By.CSS_SELECTOR, 'nav a[href="/"], nav a[href*="/direct/"]'):
            return 'unknown', '', 'Navegacion disponible; usuario no identificado'
        return 'unknown', '', 'No se pudo confirmar la sesion en esta pagina'
    except Exception as exc:
        return 'verification_error', '', f'No se pudo inspeccionar Chrome: {type(exc).__name__}'
