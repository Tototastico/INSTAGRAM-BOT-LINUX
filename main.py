import json
import threading
import time
from datetime import datetime, timedelta
from selenium_runner import comentar_en_post, acceder_caja
from comentarios import generar_comentario

def clean_text(text):
    return ''.join(c for c in text if ord(c) <= 0xFFFF)

def worker(url_post, perfil_chrome, cantidad_etiquetas, comentarios_min, tiempo_min, etiquetas_base, comentario_add):
    intervalo_seg = 60 / comentarios_min
    fin = datetime.now() + timedelta(minutes=tiempo_min)
    com_flag, driver, textarea = acceder_caja(url_post, perfil_chrome)
    if com_flag:
        while datetime.now() < fin:
            # Generar comentario con etiquetas
            comentario = generar_comentario(etiquetas_base=etiquetas_base, cantidad=cantidad_etiquetas)
            print(f"[{perfil_chrome}] Comentando: {comentario}")
            texto_limpio = clean_text(comentario)
            try:
                comentar_en_post(texto_limpio, driver, textarea)
            except Exception as e:
                print(f"[{perfil_chrome}] Error: {e}")

            time.sleep(intervalo_seg)
    else:
        print("ERROR CONECTANDO CON INSTAGRAM")

    print(f"[{perfil_chrome}] Terminó participación.")

def main():
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    url_post = config["url_post"]
    perfiles = config["perfil_chrome"]
    cantidad_etiquetas = config.get("etiquetas", 2)
    tiempo_min = config.get("exe_time", 60)
    comentarios_min = config.get("comentarios_min", 10)
    etiquetas_base = ["@camifernandl", "@karinasilvetti1", "@camisuliii", "@soyteoo", "@tobi.sirne", "@nailsconkary", "@camiiiythiago"]
    comentario_add = config["comentario"]
    threads = []
    for perfil in perfiles:
        t = threading.Thread(target=worker, args=(url_post, perfil, cantidad_etiquetas, comentarios_min, tiempo_min, etiquetas_base, comentario_add))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    print("Participación finalizada para todas las cuentas.")
    input("Presioná Enter para detener el programa...\n")

if __name__ == "__main__":
    main()
