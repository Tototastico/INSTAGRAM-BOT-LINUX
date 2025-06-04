import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
import random


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

    try:
        time.sleep(random.uniform(5, 8))

        # Esperar y encontrar el textarea de comentario
        textarea = driver.find_element(By.CSS_SELECTOR, 'textarea[aria-label="Añade un comentario..."]')
        textarea.click()
        time.sleep(random.uniform(1, 2))

        # Escribir comentario con comportamiento humano
        for letra in comentario:
            textarea.send_keys(letra)
            time.sleep(random.uniform(0.05, 0.15))

        time.sleep(random.uniform(1, 2))
        textarea.send_keys(Keys.ENTER)
        print(f"[✓] Comentario enviado con {nombre_cuenta}")

    except Exception as e:
        print(f"[!] Error al comentar con {nombre_cuenta}:", e)
    finally:
        time.sleep(random.uniform(4, 6))
        driver.quit()
        print(f"[x] Cerrando Chrome de {nombre_cuenta}")
