import json
import time
from selenium_runner import comentar_en_post
from comentarios import generar_comentario
from utils import delay_aleatorio

# Cargar configuracion
def cargar_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar_config(config, path="config.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def ejecutar_bot():
    config = cargar_config()

    url_post = config["url_post"]
    comentario_base = config["comentario"]
    delay_rango = config["delay_entre_comentarios"]
    perfil_chrome = config["perfil_chrome"]

    # Generar comentario final (puede incluir variaciones en el futuro)
    comentario_final = generar_comentario(comentario_base)

    # Ejecutar comentario
    comentar_en_post(url_post, comentario_final, perfil_chrome)

    # Esperar un tiempo aleatorio (como si fuese un humano)
    delay_aleatorio(*delay_rango)

    print("\n[✔] Comentario publicado exitosamente.")

if __name__ == "__main__":
    ejecutar_bot()
