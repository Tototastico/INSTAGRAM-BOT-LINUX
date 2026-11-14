# Concurrencia y verificación de cuentas

El límite predeterminado sigue siendo **1**. En Inicio o Actividad, `Máximo de navegadores` permite elegir 1 a 4 o `Automático`. El cambio se guarda en SQLite. `MAX_CONCURRENT_BROWSERS` sigue siendo el valor inicial si todavía no hay una elección guardada. La pantalla muestra navegadores activos, tareas y motivo de espera. El coordinador recorre toda la cola: una tarea de una cuenta ocupada no bloquea otra cuenta disponible.

Cada perfil tiene una única tarea o sesión visual activa en el coordinador y el mismo bloqueo `*.lock` en Linux. El navegador visual consume un cupo. Antes de abrir otro Chrome se consulta `MemAvailable`, la memoria PSS (o RSS si PSS no está disponible) de los árboles de procesos Chrome asociados a **perfiles reservados por el bot** y la carga de CPU. Otros Chrome del VPS ya reducen `MemAvailable`, pero no se atribuyen al bot para estimar el siguiente navegador. Sin Chrome gestionado observado se usan 768 MB como estimación inicial; con Chrome observado se agrega un margen del 20% a la memoria media por navegador, con un mínimo de 768 MB. Se reservan 1024 MB adicionales para Ubuntu y los servicios. Los navegadores admitidos que todavía arrancan consumen un cupo estimado. Si faltan métricas de RAM o CPU en Linux no se admite otro navegador hasta recuperar la medición. En automático el techo es 4; la admisión por recursos puede dejar tareas en cola incluso con cupos libres. El planificador reevalúa la cola cada 15 segundos. El servicio debe seguir con **un worker**, sin `--reload`, y bajo el `flock` de `deploy/start.sh`. SQLite usa conexiones separadas por operación, WAL y espera de 30 segundos.

`Verificar conexión` abre el perfil persistente una sola vez, protegido por los mismos bloqueos, inspecciona la página y cierra Chrome. Sólo declara `connected` cuando identifica un enlace de perfil de la navegación. Compara el usuario si el nombre registrado tiene forma de usuario de Instagram. Los nombres descriptivos con espacios no se interpretan como identificadores. `unknown` y `verification_error` no equivalen a sesión caducada. La tarjeta muestra usuario detectado, motivo y fecha. Una tarea se pausa sólo ante una señal explícita de login, verificación o usuario incorrecto; no se pulsa ningún control de autenticación. La reanudación es manual tras reconectar y revisar el perfil.

Los diagnósticos de tareas usan la misma cookie administrativa corta que el navegador visual. Ya no se solicita ni se envía `BOT_DIAGNOSTICS_TOKEN`. Si todavía no hay sesión administrativa, el panel pide la clave administrativa existente una vez. El backend rechaza solicitudes anónimas y mantiene las capturas privadas. Nginx Basic Auth por sí sola no da al backend una identidad verificable; no se confía en encabezados que un cliente pueda falsificar.

## Comprobar la admisión en Ubuntu

`/api/scheduler` muestra RAM disponible, PSS usado por Chrome del bot, RSS sin ajustar, fuente de medición, estimación del siguiente navegador, reserva, RAM requerida, carga de CPU y motivo de rechazo. PSS reparte las páginas compartidas entre procesos; por eso puede ser menor que la suma RSS. Si falta `smaps_rollup` para cualquier proceso del árbol, se usa la suma RSS completa y el panel indica `RSS (PSS no disponible)`. La swap no se cuenta como RAM disponible para admitir navegadores.

Con una tarea activa, comprobar la medición desde el mismo usuario del servicio, sustituyendo el perfil por el de esa tarea:

```bash
cd /opt/instagram-bot
sudo -u jarvisadmin .venv/bin/python -c "from webapp.resources import snapshot, admission_decision; m=snapshot(['/home/jarvisadmin/instagram-bot-data/accounts/cuenta2']); print(m); print(admission_decision(m, 1))"
```

La segunda cuenta se admite sólo si `MemAvailable` cubre la reserva de 1024 MB más la estimación incremental y la carga de CPU está bajo dos veces el número de núcleos. Si hay un Chrome recién admitido que aún no aparece en `/proc`, se reserva también su estimación. Validar con una prueba supervisada en el VPS y observar RAM y swap antes de elevar el límite.

## Actualización de Ubuntu

No ejecutar durante una tarea activa. Revisar primero el estado y tomar un respaldo consistente de SQLite con su API de backup. No copiar un archivo WAL activo con `cp`.

```bash
cd /opt/instagram-bot
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
