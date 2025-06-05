import random


def generar_comentario(etiquetas_base, cantidad=1):
    variaciones = [
        "¡Participando! 🙌 {tags}",
        "Vamos por ese premio 🔥 {tags}",
        "Espero ganar 🤞 {tags}",
        "Suerte para mí 😄 {tags}",
        "¡Allá vamos! 💪 {tags}"
    ]

    if cantidad > len(etiquetas_base):
        cantidad = len(etiquetas_base)
    seleccionados = random.sample(etiquetas_base, cantidad)
    tags = " ".join(seleccionados)

    plantilla = random.choice(variaciones)
    return plantilla.replace("{tags}", tags)