from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


class InstanceLock:
    """Не даёт запустить два процесса бота с одним и тем же токеном.

    На Windows используется именованный mutex, на Linux/macOS — flock.
    Блокировка снимается автоматически, даже если процесс упал.
    """

    def __init__(self, key: str, lock_path: Path | None = None) -> None:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        self._mutex_name = f"Global\\nft_stars_bot_{digest}"
        self._lock_path = lock_path or Path("data/bot.lock")
        self._kernel32 = None
        self._handle = None
        self._file = None
        self._acquired = False

    def acquire(self) -> bool:
        if sys.platform == "win32":
            return self._acquire_windows()
        return self._acquire_posix()

    def _acquire_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateMutexW(None, False, self._mutex_name)
        if not handle:
            return False
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False

        self._kernel32 = kernel32
        self._handle = handle
        self._acquired = True
        return True

    def _acquire_posix(self) -> bool:
        import fcntl

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self._lock_path.open("a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_file.close()
            return False

        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        self._file = lock_file
        self._acquired = True
        return True

    def release(self) -> None:
        if not self._acquired:
            return

        if self._kernel32 is not None and self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
            self._kernel32 = None

        if self._file is not None:
            import fcntl

            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None

        self._acquired = False

    def __enter__(self) -> "InstanceLock":
        if not self.acquire():
            raise RuntimeError("Экземпляр бота уже запущен")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
