# Concurrencia y verificación de cuentas

El límite predeterminado sigue siendo **1**. En Inicio o Actividad, `Máximo de navegadores` permite elegir 1 a 4 o `Automático`. El cambio se guarda en SQLite. `MAX_CONCURRENT_BROWSERS` sigue siendo el valor inicial si todavía no hay una elección guardada. La pantalla muestra navegadores activos, tareas y motivo de espera. El coordinador recorre toda la cola: una tarea de una cuenta ocupada no bloquea otra cuenta disponible.

Cada perfil tiene una única tarea o sesión visual activa en el coordinador y el mismo bloqueo `*.lock` en Linux. El navegador visual consume un cupo. Antes de abrir otro Chrome se consulta `MemAvailable`, la memoria PSS (o RSS si PSS no está disponible) de los árboles de procesos Chrome asociados a **perfiles reservados por el bot** y la carga de CPU. Otros Chrome del VPS ya reducen `MemAvailable`, pero no se atribuyen al bot para estimar el siguiente navegador. Sin Chrome gestionado observado se usan 768 MB como estimación inicial; con Chrome observado se agrega un margen del 20% a la memoria media por navegador, con un mínimo de 768 MB. Se reservan 1024 MB adicionales para Ubuntu y los servicios. Los navegadores admitidos que todavía arrancan consumen un cupo estimado. Si faltan métricas de RAM o CPU en Linux no se admite otro navegador hasta recuperar la medición. En automático el techo es 4; la admisión por recursos puede dejar tareas en cola incluso con cupos libres. El planificador reevalúa la cola cada 15 segundos. El servicio debe seguir con **un worker**, sin `--reload`, y bajo el `flock` de `deploy/start.sh`. SQLite usa conexiones separadas por operación, WAL y espera de 30 segundos.

`Verificar conexión` abre el perfil persistente una sola vez, protegido por los mismos bloqueos, inspecciona la página y cierra Chrome. Sólo declara `connected` cuando identifica un enlace de perfil de la navegación. Compara el usuario si el nombre registrado tiene forma de usuario de Instagram. Los nombres descriptivos con espacios no se interpretan como identificadores. `unknown` y `verification_error` no equivalen a sesión caducada. La tarjeta muestra usuario detectado, motivo y fecha. Una tarea se pausa sólo ante una señal explícita de login, verificación o usuario incorrecto; no se pulsa ningún control de autenticación. La reanudación es manual tras reconectar y revisar el perfil.

Los diagnósticos de tareas usan la misma cookie administrativa corta que el navegador visual. Ya no se solicita ni se envía `BOT_DIAGNOSTICS_TOKEN`. Si todavía no hay sesión administrativa, el panel pide la clave administrativa existente una vez. El backend rechaza solicitudes anónimas y mantiene las capturas privadas. Nginx Basic Auth por sí sola no da al backend una identidad verificable; no se confía en encabezados que un cliente pueda falsificar.

## Comprobar la admisión en Ubuntu

`/api/scheduler` muestra RAM disponible, PSS usado por Chrome del bot, RSS sin ajustar, fuente e intentos de medición, estimación del siguiente navegador, reserva, RAM requerida, carga de CPU y motivo de rechazo. También muestra cuántos PID integraron la última muestra, cuántos desaparecieron o provocaron un reintento, cuántos procesos vivos carecen de PSS y cuántos eran zombis o estaban terminados. PSS reparte las páginas compartidas entre procesos; por eso puede ser menor que la suma RSS. Si un proceso termina mientras se lee `/proc`, se reconstruye el árbol y se repite una muestra completa, hasta tres intentos. Un proceso sin `VmRSS` se comprueba antes de tratarlo como memoria desconocida; los zombis y terminados no consumen memoria activa. No se suman valores PSS de muestras distintas. Si persiste la rotación de procesos, se usa RSS de los supervivientes más una reserva por los PID desaparecidos (su último RSS o 768 MB si faltaba); el panel indica `RSS (procesos transitorios)`. Si un proceso sigue vivo pero su `smaps_rollup` no es legible, se usa RSS y se indica `RSS (PSS inaccesible en un proceso activo)`. Si tampoco se conoce su RSS, no se admite otro navegador. La swap no se cuenta como RAM disponible para admitir navegadores.

Con una tarea activa, comprobar la medición desde el mismo usuario del servicio, sustituyendo el perfil por el de esa tarea:

```bash
cd /home/jarvisadmin/apps/instagram-bot-linux
sudo -u jarvisadmin .venv/bin/python -c "from webapp.resources import snapshot, admission_decision; m=snapshot(['/home/jarvisadmin/instagram-bot-data/accounts/cuenta2']); print(m); print(admission_decision(m, 1))"
```

La segunda cuenta se admite sólo si `MemAvailable` cubre la reserva de 1024 MB más la estimación incremental y la carga de CPU está bajo dos veces el número de núcleos. Si hay un Chrome recién admitido que aún no aparece en `/proc`, se reserva también su estimación. Validar con una prueba supervisada en el VPS y observar RAM y swap antes de elevar el límite.

## Actualización de Ubuntu

No ejecutar durante una tarea activa. Revisar primero el estado y tomar un respaldo consistente de SQLite con su API de backup. No copiar un archivo WAL activo con `cp`.

```bash
cd /home/jarvisadmin/apps/instagram-bot-linux
git fetch origin main
git switch main
git pull --ff-only origin main
.venv/bin/python -m pytest -q
cd frontend && npm ci && npm run build && cd ..
sudo systemctl restart instagram-bot
sudo systemctl status instagram-bot --no-pager
```

El primer arranque añade `session_user` y `session_reason` a la base sin alterar cuentas, perfiles ni sesiones Chrome. Mantener el servicio con un worker y `deploy/start.sh` o un `flock` equivalente. No cambiar Nginx ni VNC para esta mejora. La verificación en el VPS con cuentas reales sigue pendiente; probar una cuenta supervisada antes de subir el límite.

## Vuelta atrás

Detener nuevas tareas, esperar o cancelar las activas, respaldar la base con SQLite, detener el servicio, volver al commit anterior y compilar su frontend. Si se restaura la base, usar el respaldo del mismo release. Las tareas cuyo comentario pudo haberse enviado se revisan manualmente antes de reanudar. No restaurar perfiles Chrome con el navegador abierto.

## Fallo al iniciar una segunda cuenta

Un `SessionNotCreatedException` en `chrome_start` ocurre antes de navegar a Instagram. Por eso no hay captura de la publicación. El inicio de ChromeDriver se serializa dentro del proceso para que dos tareas no preparen simultáneamente el binario compartido de `undetected-chromedriver`; los navegadores ya iniciados siguen pudiendo trabajar en paralelo. No se reintenta automáticamente una tarea cuyo resultado no se conoce.

El diagnóstico de esa tarea muestra RAM y swap disponibles, espacio en `/tmp` y `/dev/shm`, uso y límite de memoria y procesos del cgroup, contador de procesos terminados por OOM dentro del cgroup y si todavía hay un Chrome usando ese perfil. Son valores numéricos tomados tras la excepción; no guardan ruta de perfil ni argumentos de Chrome. Una medición posterior con `free -h` no prueba los recursos disponibles en el instante del fallo. La swap ocupada tampoco demuestra una fuga: puede contener páginas inactivas de procesos anteriores.

Si vuelve a ocurrir, revisar el diagnóstico nuevo y comparar los contadores de OOM del cgroup antes y después. Desde el VPS, consultar también `sudo journalctl -u instagram-bot -u systemd-oomd --since '15 minutes ago' --no-pager` y `sudo journalctl -k --since '15 minutes ago' --no-pager`. El registro de kernel puede estar vacío aunque el servicio tenga un límite propio de memoria o procesos. Verificar esos límites con `systemctl show instagram-bot -p MemoryMax -p TasksMax -p OOMPolicy`. Consultar `free -h` y `df -h /tmp /dev/shm /home` en el mismo momento.

Chrome guarda cachés dentro de cada perfil en disco. No borrar `Cache`, `Code Cache`, cookies ni otros archivos del perfil mientras Chrome está abierto: puede alterar sesiones existentes. El espacio libre de disco y la RAM disponible se miden por separado; limpiar la caché del perfil no corrige por sí solo un fallo de conexión de ChromeDriver.

### Preferences del perfil sobredimensionado

El panel de Inicio/Actividad avisa si `Default/Preferences` supera 8 MB y marca el perfil como bloqueado si supera 64 MB. Solo consulta el tamano del archivo: no lee su contenido ni borra caches, cookies o sesiones. La misma proteccion se aplica a la verificacion de cuenta y a la apertura visual. Si aparece un aviso de crecimiento, revisar esa cuenta antes de elevar el limite. El planificador conserva `MemAvailable`, PSS/RSS, la reserva de 1024 MB y el margen del 20%; la swap no cuenta como RAM disponible. Tres Chrome solo deben mantenerse si `/api/scheduler` muestra capacidad durante la ejecucion real.

El 16/11/2026, `cuenta1/Default/Preferences` medía 3.221.276.728 bytes. `undetected-chromedriver` lee y reescribe ese JSON entero antes de abrir Chrome. En el VPS de 3,7 GB, tres arranques del perfil terminaron con el kernel matando al Python de FastAPI por OOM; esto produjo HTTP 502 y tareas `interrupted`. El límite preventivo de 64 MB en `crear_driver()` ahora detiene solo ese perfil con un diagnóstico específico, sin abrir Chrome ni cambiar archivos. Otros perfiles pequeños pueden seguir funcionando. El límite no repara el archivo.

Para recuperar ese perfil sin perder una sesión inadvertidamente: detener el servicio cuando no haya tareas activas, cerrar cualquier Chrome manual del perfil y hacer una copia privada completa de `cuenta1` fuera del repositorio. Probar primero con **una copia** del perfil: apartar únicamente `Default/Preferences` en la copia, abrirla manualmente en el mismo usuario y comprobar la sesión en VNC. Chrome regenerará las preferencias de esa copia; las cookies y bases del perfil original permanecen intactas. Solo después de una prueba satisfactoria, apartar `Default/Preferences` del perfil original con el servicio detenido, conservar el respaldo y verificar una tarea supervisada. Si la sesión no se conserva, cerrar Chrome y restaurar el perfil original desde la copia de seguridad. No reanudar en masa tareas `interrupted`: revisar si algún comentario pudo haberse enviado antes de la caída.
