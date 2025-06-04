import random

def generar_comentario(base):
    # Podés extender esto con plantillas más complejas si querés
    variaciones = [
        "¡Participando! 🙌 {tags}",
        "Vamos por ese premio 🔥 {tags}",
        "Espero ganar 🤞 {tags}",
        "Suerte para mí 😄 {tags}",
        "¡Allá vamos! 💪 {tags}"
    ]

    etiquetas = ["@amigo1", "@amigo2", "@amigo3", "@amigo4", "@amigo5"]
    seleccionados = random.sample(etiquetas, 2)
    tags = " ".join(seleccionados)

    plantilla = random.choice(variaciones)
    return plantilla.replace("{tags}", tags)
