import time
import random
from datetime import datetime


def delay_aleatorio(min_seg, max_seg):
    segundos = random.uniform(min_seg, max_seg)
    print(f"[⏱] Esperando {segundos:.2f} segundos...")
    time.sleep(segundos)


def log(texto):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ahora}] {texto}")
