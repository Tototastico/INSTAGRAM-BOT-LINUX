# INSTAGRAM-BOT local

Panel local para administrar cuentas, sorteos, asignaciones y tareas en Linux. El envio sigue usando las funciones existentes de `selenium_runner.py`. El programa no inicia tareas automaticamente al abrirse. Para instalar en Ubuntu, consulta [DESPLIEGUE_LINUX.md](DESPLIEGUE_LINUX.md).

## Instalacion

En Ubuntu, desde la carpeta del proyecto:

```bash
bash deploy/install.sh
```

Para arrancar el panel compilado con variables de entorno configuradas:

```bash
bash deploy/start.sh
```

Abri `http://127.0.0.1:8000/`. El panel solo escucha en el servidor. Para desarrollar la UI, usa `npm run dev` dentro de `frontend` y abre `http://127.0.0.1:5173/`, manteniendo la API en el puerto 8000.

Al abrir Chrome, el runner lee la version principal de Chrome o Chromium y solicita un ChromeDriver compatible. Si el navegador esta instalado en una ruta no estandar, define antes de arrancar el panel:

```bash
export CHROME_BINARY=/ruta/al/chrome
```

Si Chrome se actualiza mientras el panel esta abierto, reinicia el panel antes de iniciar otra tarea.

## Primer uso

Al primer arranque se crea una base nueva en `BOT_DB_PATH`. `config.json` solo se importa si se indica expresamente al crear la aplicacion. Los perfiles se crean en `BOT_ACCOUNTS_DIR`; `cuenta1` y `accounts/cuenta1` resuelven al mismo directorio. No copies perfiles de Windows: inicia sesion de nuevo en Linux.

Revisa la cuenta y el sorteo antes de iniciar la primera tarea. Cada sorteo guarda su fecha y hora de finalizacion opcionales y el numero de menciones requerido; las asignaciones heredan ese numero. Si no se indica hora, se considera el final del dia en la zona horaria local del navegador. La fecha solo clasifica y avisa: no detiene tareas en ejecucion. En **Sorteos** se muestran por defecto los activos, ordenados por fecha descendente; los filtros permiten ver finalizados, archivados o todos y cambiar el orden. En **Asignaciones > Etiquetas disponibles** carga una lista una vez y luego selecciona varias para cada asignacion. Cada asignacion conserva su frecuencia, texto y duracion propios. **Indefinida** continua hasta pausarla, cancelarla, encontrar un bloqueo posible o fallar. Dos asignaciones del mismo perfil se encolan. Por defecto se ejecuta un navegador a la vez; el limite se configura con MAX_CONCURRENT_BROWSERS.

**Inicio** muestra sorteos por finalizar, activos, finalizados, mas comentados y clics diarios. Son clics en Publicar, no confirmaciones verificadas. El recordatorio se configura con 1, 3, 6, 12, 24, 48 o 72 horas de anticipacion; aparece en Inicio y, si habilitas la campana, como notificacion del navegador mientras el panel este abierto. Se emite una vez por sorteo, fecha/hora y anticipacion elegida en ese navegador. Con sorteos sin hora, el aviso se calcula respecto del final del dia. No hay un servicio de notificaciones en segundo plano ni se recuperan avisos de sorteos ya vencidos; otros canales quedan pendientes.

Al iniciar cada tarea, despues de abrir la publicacion, Selenium intenta leer una sola vez el contador visible junto al icono **Comentar**. Guarda el numero y la fecha de medicion en el sorteo; en **Sorteos** se puede ver y ordenar por **Comentarios IG**. Al iniciar otra tarea del mismo sorteo vuelve a consultarlo. Si el contador no aparece, usa un formato abreviado o cambia la interfaz, se registra un evento y se conserva la ultima medicion valida; la tarea sigue comentando. No se navega a otra pagina ni se altera la caja de comentarios para medirlo. Es una lectura de la interfaz, no una metrica oficial ni un conteo en tiempo real. La [API oficial de Instagram](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api) es otra opcion para publicaciones elegibles, pero requiere una app, permisos y cuentas profesionales. Dividir los clics propios por ese total seria una participacion aproximada, no una probabilidad de ganar: un clic no garantiza un comentario valido y las reglas del sorteo pueden variar.

Cada tarea nueva guarda la cuenta y el sorteo con los que se creo. Editar una asignacion despues de completar o cancelar sus tareas no mueve el historial: los clics anteriores siguen en el sorteo original. Las tareas en curso aparecen primero y resaltadas en verde. No se puede editar una asignacion con tareas activas, pausadas o interrumpidas que todavia puedan reanudarse. Al actualizar una base antigua, las tareas previas se vinculan al sorteo al que apunta su asignacion en ese momento; si esa asignacion ya habia cambiado, la base no conserva el sorteo anterior. En **Actividad > Corregir historial** se pueden indicar IDs de tareas terminadas (por ejemplo `20-24, 9`) y asignarles manualmente su sorteo real. La correccion queda registrada como evento y no altera tareas activas.

Pausa y cancelacion se aplican entre comentarios, despues de que termine la accion en curso. Una tarea interrumpida por cierre del programa requiere reanudacion manual. El contador **Clics** refleja que Selenium hizo clic en Publicar; **Confirmados** solo contaria una comprobacion independiente, que aun no existe.

En Inicio y Actividad, el boton **Ver logs y error** de cada tarea abre su historial reciente y el error completo asociado. Los reintentos al buscar el textarea se registran como eventos; los fallos nuevos incluyen el tipo de excepcion y la etapa. Si el textarea es reemplazado antes de escribir, se busca de nuevo y se comprueba que este vacio. No se reintenta automaticamente un comentario una vez iniciada la escritura o el clic, porque su resultado puede ser incierto.

Antes de escribir cada comentario, el panel comprueba que el textarea este vacio. Si conserva texto, lo trata como posible bloqueo o comentario pendiente: pausa la tarea y las tareas en cola de esa cuenta, cierra Chrome y muestra un aviso persistente. El icono de campana permite habilitar notificaciones del navegador mientras el panel esta abierto. Revisa la cuenta en Instagram, pulsa **Marcar revisada** y luego reanuda manualmente la tarea; el programa no borra el texto ni reintenta ese comentario por si solo.

No ejecutes `main.py` y el panel al mismo tiempo con el mismo perfil de Chrome. El flujo original permanece disponible como respaldo. Si Chrome muestra login, desafio o CAPTCHA, resuelvelo manualmente. El panel detecta las URL de login y desafio; si la caja de comentarios no aparece, la tarea se detiene con un error.

## Pruebas

```powershell
python -m pytest -q tests
npm run build --prefix frontend
node --test frontend/src/draws.test.mjs
```

Las pruebas automatizadas simulan Selenium. Antes de usar una cuenta real, hace una prueba supervisada con una asignacion corta y revisa la actividad. La publicacion real no puede verificarse sin una sesion de Chrome disponible.
