from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path


def resolved_regular_file(path: Path) -> Path:
    """Resolve a config symlink without replacing it; reject broken/non-file targets."""
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OSError(f"Unsafe or broken configuration path {path}: {exc}") from exc
    if not target.is_file():
        raise OSError(f"Configuration target is not a regular file: {target}")
    return target


def _copy_xattrs(source: Path, destination: Path) -> None:
    """Copy extended attributes, including Linux POSIX ACL xattrs where supported."""
    if not all(hasattr(os, name) for name in ("listxattr", "getxattr", "setxattr")):
        return
    try:
        names = os.listxattr(source)
    except OSError:
        return
    for name in names:
        try:
            os.setxattr(destination, name, os.getxattr(source, name))
        except OSError as exc:
            raise OSError(f"Could not preserve extended attribute {name}: {exc}") from exc


def atomic_write(path: Path, content: str) -> None:
    """Replace the resolved regular file atomically, preserving symlinks and metadata."""
    target = resolved_regular_file(path)
    current = target.stat()
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
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
        _copy_xattrs(target, temp_path)
        os.replace(temp_path, target)
        directory_fd = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def safe_create_directory(path: Path, uid: int, gid: int, mode: int) -> None:
    path.mkdir(parents=True, mode=mode, exist_ok=True)
    set_directory_metadata(path, uid, gid, mode)


def set_directory_metadata(path: Path, uid: int, gid: int, mode: int) -> None:
    if not path.is_dir() or path.is_symlink():
        raise OSError(f"Refusing to change non-directory or symlink: {path}")
    os.chmod(path, mode)
    if os.geteuid() == 0:
        os.chown(path, uid, gid)


def remove_empty_directory(path: Path) -> None:
    """Only remove an empty directory; data deletion is intentionally unsupported."""
    path.rmdir()


def copy_preserving(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
