import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import time
import random
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains

def crear_driver(nombre_cuenta):
    options = uc.ChromeOptions()
    
    # Ruta absoluta al perfil
    perfil_path = f"C:/Users/user/Desktop/INSTAGRAM-BOT/accounts/{nombre_cuenta}"
    options.add_argument(f"--user-data-dir={perfil_path}")
    
    # Parámetros adicionales para evitar detección
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    driver = uc.Chrome(options=options)
    return driver



def comentar_en_post(url_post, comentario, nombre_cuenta):
    print(f"[+] Iniciando sesión con la cuenta: {nombre_cuenta}")
    driver = crear_driver(nombre_cuenta)
    driver.get(url_post)
    
    driver.maximize_window()
    actions = ActionChains(driver)
    # Mover el mouse a coordenadas (10, 10) dentro de la ventana y hacer click

    
    time.sleep(3)  # tiempo para que cargue la página
    driver.execute_script("window.focus(); document.activeElement.blur();")
    body = driver.find_element(By.TAG_NAME, "body")
    actions.move_by_offset(10, 10).click().perform()

    body.click()  # quita foco de la barra



    try:
        time.sleep(random.uniform(5, 8))

        # Intentar encontrar el textarea confiable
        for intento in range(3):
            try:
                wait = WebDriverWait(driver, 15)
                body = wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                print(body)
                ActionChains(driver).move_to_element(body).click().perform()
                textarea = driver.find_element(By.CSS_SELECTOR, 'textarea[aria-label="Añade un comentario..."]')
                #textarea = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "textarea[placeholder='Añade un comentario...']")))
                textarea.click()
                print(textarea)
                break
            except (StaleElementReferenceException, NoSuchElementException):
                print(f"[!] Reintentando encontrar textarea (intento {intento + 1})...")
                time.sleep(2)
        else:
            print("[X] No se pudo encontrar el textarea luego de varios intentos.")
            return

        time.sleep(random.uniform(1, 2))

        for letra in comentario:
            textarea.send_keys(letra)
            time.sleep(random.uniform(0.05, 0.15))

        time.sleep(random.uniform(1, 2))
        textarea.send_keys(Keys.ENTER)
        print("[✓] Comentario enviado correctamente.")

    except Exception as e:
        print("[!] Error al comentar:", e)
    finally:
        time.sleep(random.uniform(4, 6))
        driver.quit()