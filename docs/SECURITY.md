# Seguridad y Acceso Seguro

---

## 1. Exposición de Red
- **El panel web NUNCA debe exponerse directamente a Internet.**
- Uvicorn está configurado explícitamente para escuchar en `127.0.0.1:8000` (localhost).
- El acceso administrativo debe realizarse exclusivamente a través de túneles SSH cifrados:
  ```bash
  ssh -N -L 18000:127.0.0.1:8000 usuario@vps
  ```

---

## 2. Protección de Archivos y Permisos
- El usuario `instagram-bot` no tiene privilegios de superusuario (`sudo`).
- Permisos asignados en `/var/lib/instagram-bot`:
  - `accounts/` (perfiles y cookies de Chrome): `chmod 700` (solo el usuario de servicio puede leer y escribir).
  - `data/` (base SQLite): `chmod 700`.
  - `backups/`: `chmod 700`.
  - `/etc/instagram-bot/instagram-bot.env`: `chmod 640`, propiedad `root:instagram-bot`.

---

## 3. Inicio de Sesión Manual de Cuentas (VNC / SSH X11)
Para iniciar sesión por primera vez en una cuenta de Instagram en el VPS:

**Opción recomendada: Túnel SSH con X11 Forwarding**
```bash
# Conectarse permitiendo interfaz gráfica vía SSH
ssh -X usuario@vps

# Abrir Chrome en el perfil de la cuenta deseada:
sudo -u instagram-bot google-chrome-stable --user-data-dir=/var/lib/instagram-bot/accounts/cuenta1
```
Inicia sesión en Instagram, resuelve los desafíos 2FA o SMS correspondientes y cierra el navegador. La sesión y las cookies quedarán almacenadas en `/var/lib/instagram-bot/accounts/cuenta1`.
