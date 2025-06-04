import sys
import json
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QVBoxLayout, QPushButton,
    QSpinBox, QTextEdit, QListWidget, QListWidgetItem, QAbstractItemView
)


class SorteoInstagramGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Participación Automática de Sorteos en Instagram")
        self.setGeometry(100, 100, 500, 500)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Link del post
        layout.addWidget(QLabel("Link de la publicación de Instagram:"))
        self.link_input = QLineEdit()
        layout.addWidget(self.link_input)

        # Selección múltiple de cuentas
        layout.addWidget(QLabel("Seleccioná tus cuentas de Instagram:"))
        self.account_list = QListWidget()
        self.account_list.setSelectionMode(QAbstractItemView.MultiSelection)
        cuentas = ["@tototastico"]
        for cuenta in cuentas:
            item = QListWidgetItem(cuenta)
            self.account_list.addItem(item)
        layout.addWidget(self.account_list)

        # Cantidad de etiquetas
        layout.addWidget(QLabel("Cantidad de etiquetas por comentario:"))
        self.tags_spin = QSpinBox()
        self.tags_spin.setRange(1, 99999)
        layout.addWidget(self.tags_spin)

        # Texto complementario
        layout.addWidget(QLabel("Texto complementario para comentarios (opcional):"))
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("Ej: ¡Ojalá gane! 🍀")
        layout.addWidget(self.text_input)

        # Tiempo de ejecución
        layout.addWidget(QLabel("Tiempo de ejecución (minutos):"))
        self.time_spin = QSpinBox()
        self.time_spin.setRange(1, 99999)
        layout.addWidget(self.time_spin)

        # Comentarios por minuto
        layout.addWidget(QLabel("Comentarios por minuto:"))
        self.comments_spin = QSpinBox()
        self.comments_spin.setRange(1, 99999)
        layout.addWidget(self.comments_spin)

        # Botón de iniciar
        self.start_button = QPushButton("Iniciar participación")
        self.start_button.clicked.connect(self.mostrar_config)
        layout.addWidget(self.start_button)

        self.setLayout(layout)

    #def mostrar_config(self):
    #    cuentas_seleccionadas = [item.text() for item in self.account_list.selectedItems()]
    #    print("Cuentas seleccionadas:", cuentas_seleccionadas)
    #    print("Link:", self.link_input.text())
    #    print("Cantidad de etiquetas:", self.tags_spin.value())
    #    print("Texto:", self.text_input.toPlainText())
    #    print("Tiempo de ejecución (min):", self.time_spin.value())
    #    print("Comentarios por minuto:", self.comments_spin.value())
#
    #import json

    def mostrar_config(self):
        cuentas_seleccionadas = [f"{item.text()[1:]}" for item in self.account_list.selectedItems()]
        link = self.link_input.text()
        cantidad_etiquetas = self.tags_spin.value()
        texto_complementario = self.text_input.toPlainText()
        tiempo_ejecucion = self.time_spin.value()
        comentarios_por_minuto = self.comments_spin.value()

        # Armar el comentario base combinando texto complementario y etiquetas
        # Ejemplo simple: "texto + etiquetas separadas por espacios"
        comentario_base = f"{texto_complementario} " + " ".join([f"@{c.lower()}" for c in cuentas_seleccionadas])

        # Configuración a guardar
        config = {
            "url_post": link,
            "comentario": texto_complementario.strip(),
            "perfil_chrome": cuentas_seleccionadas,   # Lo podés mapear según la cuenta o dejar fijo
            "etiquetas": cantidad_etiquetas,
            "exe_time": tiempo_ejecucion,
            "comentarios_min": comentarios_por_minuto
        }

        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print("Configuración guardada en config.json")
        print(config)



if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SorteoInstagramGUI()
    window.show()
    sys.exit(app.exec_())
