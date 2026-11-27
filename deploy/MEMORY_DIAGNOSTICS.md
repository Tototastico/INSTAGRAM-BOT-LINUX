# Capturar una falla de memoria

El recolector lee `/proc` y el cgroup de `instagram-bot.service`. No inicia Chrome,
no lee perfiles ni modifica tareas. Guarda nombres de procesos y tamaños de memoria,
sin argumentos de comandos, URLs, cookies ni variables de entorno.

En una terminal SSH del VPS, antes de iniciar **una sola** tarea de prueba:

```bash
cd /home/jarvisadmin/apps/instagram-bot-linux
python3 deploy/collect_memory.py --duration-seconds 600 --interval-seconds 2
```

El programa muestra la ruta del archivo privado `memory-*.jsonl` al terminar.
Mientras registra, iniciar la tarea desde el panel. Se puede detener con `Ctrl+C`;
las muestras ya escritas permanecen en el archivo. El directorio tiene permisos
`0700` y cada archivo `0600`.

Revisar los valores mínimos y máximos de la salida. `mem_available_mb` es la RAM
recuperable; `bot_memory_mb` incluye caché de archivos. Comparar este último con
`bot_anon_mb` y `bot_file_cache_mb` para distinguir memoria de procesos y caché.
`bot_swap_mb` corresponde al servicio; `swap_used_mb` incluye todo el servidor.
`bot_oom_kill_count` que aumenta confirma una muerte por falta de memoria.

Para ver el contexto del kernel después de una falla, con acceso sudo:

```bash
sudo journalctl -k --since '15 minutes ago' --no-pager |
  grep -Ei 'out of memory|oom-kill|killed process' | tail -30
```

No usar `killall chrome`, borrar cachés o reiniciar otros servicios como respuesta
automática: primero identificar el proceso y el instante que disparan el pico.
