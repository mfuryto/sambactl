from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """Replace path atomically while preserving its mode and ownership."""
    current = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IMODE(current.st_mode))
        try:
            os.chown(temp_path, current.st_uid, current.st_gid)
        except PermissionError:
            if os.geteuid() == 0:
                raise
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def safe_create_directory(path: Path, uid: int = 0, gid: int = 0, mode: int = 0o2770) -> None:
    path.mkdir(parents=True, mode=mode, exist_ok=True)
    os.chmod(path, mode)
    if os.geteuid() == 0:
        os.chown(path, uid, gid)


def remove_empty_directory(path: Path) -> None:
    """Only remove an empty directory; data deletion is intentionally unsupported."""
    path.rmdir()


def copy_preserving(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
