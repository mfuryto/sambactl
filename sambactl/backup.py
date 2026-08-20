from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path

AUTOMATIC_RE = re.compile(r"^smb\.conf\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?\.bak$")


class BackupManager:
    def __init__(self, config_path: Path, directory: Path, retention: int = 10) -> None:
        self.config_path = config_path
        self.directory = directory
        self.retention = retention

    def ensure_directory(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.stat().st_mode & 0o077:
            self.directory.chmod(0o700)

    def _copy(self, destination: Path) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=self.directory)
        temporary_path = Path(temporary)
        try:
            os.close(fd)
            fd = -1
            shutil.copy2(self.config_path, temporary_path)
            source_mode = stat.S_IMODE(self.config_path.stat().st_mode)
            temporary_path.chmod(source_mode)
            temporary_path.replace(destination)
        finally:
            if fd >= 0:
                os.close(fd)
            temporary_path.unlink(missing_ok=True)

    def create(self, *, now: datetime | None = None) -> Path:
        self.ensure_directory()
        stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
        destination = self.directory / f"smb.conf.{stamp}.bak"
        counter = 1
        while destination.exists():
            destination = self.directory / f"smb.conf.{stamp}-{counter}.bak"
            counter += 1
        self._copy(destination)
        self.rotate()
        return destination

    def create_preserved(self, name: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip(".-")
        if not safe:
            raise ValueError("Backup name must contain letters or numbers")
        self.ensure_directory()
        destination = self.directory / f"manual-{safe}.bak"
        if destination.exists():
            raise FileExistsError(destination)
        self._copy(destination)
        return destination

    def list(self) -> list[Path]:
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)

    def rotate(self) -> None:
        # copy2 preserves smb.conf mtime, so filename timestamps are authoritative here.
        automatic = sorted(
            (path for path in self.list() if AUTOMATIC_RE.match(path.name)),
            key=lambda path: path.name,
            reverse=True,
        )
        for obsolete in automatic[self.retention :]:
            obsolete.unlink()
