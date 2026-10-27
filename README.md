# INSTAGRAM-BOT local

Panel local para administrar cuentas, sorteos, asignaciones y tareas en Windows. El envio sigue usando las funciones existentes de `selenium_runner.py`. El programa no inicia tareas automaticamente al abrirse.

## Instalacion

Desde PowerShell, en la carpeta del proyecto:

```powershell
python -m pip install -r requirements.txt -r requirements-web.txt
cd frontend
$env:NODE_USE_SYSTEM_CA='1'
npm install
npm run build
cd ..
```

`NODE_USE_SYSTEM_CA` solo es necesario si npm no reconoce los certificados de Windows. Para arrancar el panel compilado:

```powershell
python -m uvicorn webapp.api:app --host 127.0.0.1 --port 8000
```

Abri `http://127.0.0.1:8000/`. El panel solo escucha en esta PC. Para desarrollar la UI, usa `npm run dev` dentro de `frontend` y abre `http://127.0.0.1:5173/`, manteniendo la API en el puerto 8000.

Al abrir Chrome, el runner lee la version principal del `chrome.exe` instalado y solicita un ChromeDriver compatible. Esto ocurre de forma independiente en cada PC. Si Chrome esta instalado en una ruta no estandar, define antes de arrancar el panel:

```powershell
$env:INSTAGRAM_BOT_CHROME_BINARY = 'D:\Apps\Chrome\chrome.exe'
```

Si Chrome se actualiza mientras el panel esta abierto, reinicia el panel antes de iniciar otra tarea.

## Primer uso

Al primer arranque se importa `config.json` a `data/bot.sqlite3` una sola vez. El archivo original no se modifica. Los perfiles de Chrome no se mueven: el campo `profile_arg` conserva el argumento original, incluido `accounts/cuenta1`, que el runner resuelve bajo `E:/tobias/INSTAGRAM-BOT/accounts/`.

Revisa la cuenta y el sorteo importados antes de iniciar la primera tarea. Crea asignaciones adicionales en el panel; cada una tiene duracion, frecuencia, etiquetas y texto propios. Dos asignaciones del mismo perfil se encolan. Cuentas con perfiles diferentes pueden ejecutarse a la vez.

Pausa y cancelacion se aplican entre comentarios, despues de que termine la accion en curso. Una tarea interrumpida por cierre del programa requiere reanudacion manual. El contador **Clics** refleja que Selenium hizo clic en Publicar; **Confirmados** solo contaria una comprobacion independiente, que aun no existe.

No ejecutes `main.py` y el panel al mismo tiempo con el mismo perfil de Chrome. El flujo original permanece disponible como respaldo. Si Chrome muestra login, desafio o CAPTCHA, resuelvelo manualmente. El panel detecta las URL de login y desafio; si la caja de comentarios no aparece, la tarea se detiene con un error.

## Pruebas

```powershell
python -m pytest -q tests
npm run build --prefix frontend
```

Las pruebas automatizadas simulan Selenium. Antes de usar una cuenta real, hace una prueba supervisada con una asignacion corta y revisa la actividad. La publicacion real no puede verificarse sin una sesion de Chrome disponible.
