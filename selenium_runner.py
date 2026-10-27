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

def crear_driver(nombre_cuenta):
    chrome_executable, chrome_major = chrome_binary_and_major()
    options = uc.ChromeOptions()
    perfil_path = f"E:/tobias/INSTAGRAM-BOT/accounts/{nombre_cuenta}"
    options.add_argument(f"--user-data-dir={perfil_path}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options, browser_executable_path=chrome_executable, version_main=chrome_major)
    return driver

def acceder_caja(url_post, nombre_cuenta):
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

        for intento in range(3):
            try:
                textarea = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'textarea[aria-label="Añade un comentario..."]')
                ))
                driver.execute_script("arguments[0].scrollIntoView(true);", textarea)
                driver.execute_script("arguments[0].focus();", textarea)
                actions.move_to_element(textarea).click().perform()
                time.sleep(0.5)
                return True, driver, textarea
            except (StaleElementReferenceException, NoSuchElementException) as e:
                print(f"[!] Reintentando encontrar textarea (intento {intento + 1})... {e}")
                time.sleep(2)
        else:
            print("[X] No se pudo encontrar el textarea luego de varios intentos.")
            return False, driver, None

        return True, driver, textarea

    except Exception as e:
        print("[!] Error al comentar:", e)
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
