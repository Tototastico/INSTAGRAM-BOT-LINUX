import os
import sys
from pathlib import Path

# Raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Variables de entorno estándar
# En Linux: /var/lib/instagram-bot/accounts
# En Windows: <PROJECT_ROOT>/accounts
def get_accounts_dir() -> Path:
    env_val = os.environ.get("INSTAGRAM_ACCOUNTS_DIR")
    if env_val:
        return Path(env_val).resolve()
    return (PROJECT_ROOT / "accounts").resolve()

# En Linux: /var/lib/instagram-bot/data/bot.sqlite3
# En Windows: <PROJECT_ROOT>/data/bot.sqlite3
def get_db_path() -> Path:
    env_val = os.environ.get("INSTAGRAM_BOT_DB_PATH")
    if env_val:
        return Path(env_val).resolve()
    return (PROJECT_ROOT / "data" / "bot.sqlite3").resolve()

def get_chrome_binary() -> str | None:
    return os.environ.get("INSTAGRAM_BOT_CHROME_BINARY")

def resolve_profile_path(profile_arg: str, accounts_dir: Path | None = None) -> str:
    """
    Resuelve el argumento de perfil a una ruta canónica absoluta.
    Soporta:
      - 'cuenta1' -> <ACCOUNTS_DIR>/cuenta1
      - 'accounts/cuenta1' -> <ACCOUNTS_DIR>/cuenta1
      - 'accounts\\cuenta1' -> <ACCOUNTS_DIR>/cuenta1
    En Windows se preserva el comportamiento en minúsculas histórico si corresponde,
    pero en Linux se respeta estrictamente el case-sensitive del sistema.
    """
    if not profile_arg or not str(profile_arg).strip():
        raise ValueError("Ruta de perfil inválida")

    clean = str(profile_arg).strip().replace("\\", "/")
    path = Path(clean)

    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Ruta de perfil inválida")

    parts = list(path.parts)
    if parts and parts[0].lower() == "accounts":
        parts = parts[1:]

    if len(parts) != 1 or parts[0] in ("", "."):
        raise ValueError("Usá un nombre de perfil, por ejemplo cuenta1")

    base_dir = (accounts_dir or get_accounts_dir()).resolve()
    folder_name = parts[0]

    # En Linux respetamos mayúsculas/minúsculas exactas.
    # Si la carpeta ya existe con un case específico en disco, la preservamos.
    target_path = base_dir / folder_name

    if sys.platform == "win32":
        return str(target_path.resolve()).lower()
    else:
        return str(target_path.resolve())
