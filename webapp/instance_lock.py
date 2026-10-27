import os
import sys
from pathlib import Path


class SingleInstanceLock:
    """
    Garantiza que solo una instancia del bot / servidor se ejecute simultáneamente.
    En Linux utiliza fcntl.flock (advisory lock en archivo).
    En Windows utiliza msvcrt.locking.
    """
    def __init__(self, lock_path: Path | str | None = None):
        if lock_path is None:
            # Por defecto en Linux /tmp/instagram-bot.lock o en la carpeta data
            if sys.platform != "win32":
                lock_path = Path("/tmp/instagram-bot.lock")
            else:
                from .paths import PROJECT_ROOT
                lock_path = PROJECT_ROOT / "data" / "instagram-bot.lock"
        self.lock_path = Path(lock_path)
        self.file_handle = None
        self.is_locked = False

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.file_handle = open(self.lock_path, "a+")
            if sys.platform == "win32":
                import msvcrt
                # Posicionarse al inicio y bloquear 1 byte
                self.file_handle.seek(0)
                msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            self.is_locked = True
            # Escribir el PID actual para facilitar diagnóstico
            self.file_handle.seek(0)
            self.file_handle.truncate()
            self.file_handle.write(f"{os.getpid()}\n")
            self.file_handle.flush()
            return True
        except (BlockingIOError, OSError, PermissionError):
            if self.file_handle:
                try:
                    self.file_handle.close()
                except Exception:
                    pass
                self.file_handle = None
            self.is_locked = False
            return False

    def release(self):
        if not self.is_locked or not self.file_handle:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self.file_handle.seek(0)
                msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        finally:
            try:
                self.file_handle.close()
            except Exception:
                pass
            self.file_handle = None
            self.is_locked = False
