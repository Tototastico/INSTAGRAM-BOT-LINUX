import random


def generar_comentario(etiquetas_base, cantidad=1):
    variaciones = [
        "🙌 {tags}",
        "🔥 {tags}",
        "Espero ganar 🤞 {tags}",
        "Suerteee 😄 {tags}",
        "💪 {tags}"
    ]

    if cantidad > len(etiquetas_base):
        cantidad = len(etiquetas_base)
    seleccionados = random.sample(etiquetas_base, cantidad)
    tags = " ".join(seleccionados)

    plantilla = random.choice(variaciones)
    return plantilla.replace("{tags}", tags)