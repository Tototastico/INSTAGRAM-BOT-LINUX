# Guía de Instalación en Ubuntu Linux VPS

Esta guía describe el procedimiento paso a paso para preparar un VPS Ubuntu (22.04 LTS o 24.04 LTS) x86-64 desde cero.

## 1. Requisitos Mínimos del Servidor
- **CPU:** 1 vCPU (Recomendado 2 vCPUs para ejecutar Chrome y Xvfb con fluidez).
- **RAM:** 2 GB mínimo (Recomendado 4 GB).
- **Disco:** 20 GB SSD.
- **Sistema Operativo:** Ubuntu 22.04 LTS o Ubuntu 24.04 LTS (x86_64).
- **Puertos de Red:** Puerto SSH (22 u otro personalizado). **No abrir el puerto 8000 públicamente.**

---

## 2. Transferencia del Código al VPS
Desde tu máquina local, podés clonar el repositorio o sincronizarlo mediante `rsync` o `scp`:

```bash
# Opción con Git:
git clone -b feat/linux-vps-migration https://github.com/usuario/INSTAGRAM-BOT.git /opt/instagram-bot/repo
cd /opt/instagram-bot/repo
```

---

## 3. Ejecución del Instalador Base
El script `deploy/linux/install.sh` se encarga de:
1. Validar la arquitectura x86-64 y sistema operativo.
2. Instalar paquetes de sistema (Python 3, venv, Xvfb, fuentes, librerías gráficas de Chrome).
3. Instalar Node.js LTS (para Vite/React).
4. Descargar e instalar la versión oficial estable de Google Chrome.
5. Crear el usuario de sistema `instagram-bot` con permisos restringidos.
6. Crear directorios persistentes en `/var/lib/instagram-bot` (`accounts`, `data`, `backups`).
7. Crear el entorno virtual común en `/opt/instagram-bot/venv`.
8. Configurar el archivo de variables `/etc/instagram-bot/instagram-bot.env`.
9. Registrar las unidades systemd.

Ejecutar:
```bash
sudo chmod +x deploy/linux/*.sh
sudo ./deploy/linux/install.sh
```

---

## 4. Estructura de Directorios Resultante

```text
/opt/instagram-bot/
├── current -> releases/<timestamp>    # Enlace simbólico atómico a la versión activa
├── releases/                          # Versiones históricas inmutables del código
│   └── 20261027_120000/
└── venv/                              # Entorno virtual de Python compartido

/var/lib/instagram-bot/                # DATOS PERSISTENTES (nunca se borran al actualizar)
├── accounts/                          # Perfiles de Chrome con sesiones de Instagram
├── data/                              # Base de datos bot.sqlite3
└── backups/                           # Copias de seguridad atómicas

/etc/instagram-bot/
└── instagram-bot.env                  # Variables de entorno seguras (chmod 640)
```
