import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import time
import random
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from webapp.chrome_binary import chrome_binary_and_major
from webapp.db import profile_path
from webapp.settings import ensure_private_dir, headless
from pathlib import Path

COMMENT_TEXTAREA_SELECTOR = 'textarea[aria-label="Añade un comentario..."]'


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
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options, browser_executable_path=chrome_executable,
                       version_main=chrome_major, use_subprocess=False)
    return driver

def acceder_caja(url_post, nombre_cuenta, on_log=None):
    print(f"[+] Iniciando sesión con la cuenta: {nombre_cuenta}")
    driver = crear_driver(nombre_cuenta)
    try:
        driver.get(url_post)
        driver.maximize_window()
        actions = ActionChains(driver)
        time.sleep(2)
        driver.execute_script("window.focus(); document.activeElement.blur();")
        body = driver.find_element(By.TAG_NAME, "body")
        actions.move_by_offset(10, 10).click().perform()
        body.click()

        time.sleep(random.uniform(5, 8))
        wait = WebDriverWait(driver, 15)

        last_error = None
        for intento in range(3):
            try:
                textarea = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, COMMENT_TEXTAREA_SELECTOR)
                ))
                driver.execute_script("arguments[0].scrollIntoView(true);", textarea)
                driver.execute_script("arguments[0].focus();", textarea)
                actions.move_to_element(textarea).click().perform()
                time.sleep(0.5)
                return True, driver, textarea
            except (StaleElementReferenceException, NoSuchElementException) as e:
                last_error = e
                report(f"[!] Reintentando encontrar textarea (intento {intento + 1}/3): {type(e).__name__}",
                       on_log, 'selenium_retry')
                time.sleep(2)
        else:
            report(f"[X] No se pudo encontrar el textarea luego de varios intentos: {type(last_error).__name__}",
                   on_log, 'selenium_error')
            return False, driver, None

        return True, driver, textarea

    except Exception as e:
        summary = str(e).splitlines()[0] if str(e) else ''
        report(f"[!] Error al abrir la caja de comentarios: {type(e).__name__}: {summary}",
               on_log, 'selenium_error')
        return False, driver, None
    #finally:
    #    time.sleep(random.uniform(4, 6))
    #    driver.quit()


def comentar_en_post(comentario, driver, textarea):
    wait = WebDriverWait(driver, 5)
    for letra in comentario:
        textarea.send_keys(letra)
        time.sleep(random.uniform(0.05, 0.15))

    time.sleep(random.uniform(1, 2))
    # Buscar el botón "Publicar"
    publicar_btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//div[@role="button" and text()="Publicar"]')
    ))
    driver.execute_script("arguments[0].scrollIntoView(true);", publicar_btn)
    time.sleep(0.5)
    driver.execute_script("arguments[0].click();", publicar_btn)
    print("[✓] Comentario enviado correctamente.")
