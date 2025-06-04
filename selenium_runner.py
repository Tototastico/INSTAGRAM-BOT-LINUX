import undetected_chromedriver.v2 as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
import random


def comentar_en_post(url_post, comentario, perfil_chrome):
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={perfil_chrome}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    driver = uc.Chrome(options=options)
    driver.get(url_post)

    try:
        time.sleep(random.uniform(5, 8))

        # Encontrar el textarea
        textarea = driver.find_element(By.CSS_SELECTOR, "textarea")
        textarea.click()
        time.sleep(random.uniform(1, 2))

        for letra in comentario:
            textarea.send_keys(letra)
            time.sleep(random.uniform(0.05, 0.15))

        time.sleep(random.uniform(1, 2))
        textarea.send_keys(Keys.ENTER)

    except Exception as e:
        print("[!] Error al comentar:", e)
    finally:
        time.sleep(random.uniform(4, 6))
        driver.quit()
