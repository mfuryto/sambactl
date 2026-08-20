from __future__ import annotations

import fcntl
import os
from collections.abc import Callable
from pathlib import Path

from sambactl.backup import BackupManager
from sambactl.models import OperationResult
from sambactl.samba.config import SambaConfig, file_fingerprint
from sambactl.samba.service import SambaServiceManager
from sambactl.samba.validation import Validator
from sambactl.system.filesystem import atomic_write


class ExternalChangeError(RuntimeError):
    pass


class ConfigTransaction:
    def __init__(
        self,
        config_path: Path,
        backups: BackupManager,
        validator: Validator,
        services: SambaServiceManager,
        *,
        lock_path: Path | None = None,
    ) -> None:
        self.config_path = config_path
        self.backups = backups
        self.validator = validator
        self.services = services
        self.lock_path = lock_path or Path("/run/sambactl.lock")
        self.fingerprint = file_fingerprint(config_path)

    def changed_externally(self) -> bool:
        return file_fingerprint(self.config_path) != self.fingerprint

    def refresh(self) -> None:
        self.fingerprint = file_fingerprint(self.config_path)

    def apply(self, description: str, mutate: Callable[[SambaConfig], None]) -> OperationResult:
        if os.geteuid() != 0:
            return OperationResult(False, "This operation requires root privileges")
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                return self._apply_locked(description, mutate)
        except OSError as exc:
            return OperationResult(False, f"Could not lock configuration: {exc}")

    def _apply_locked(
        self, description: str, mutate: Callable[[SambaConfig], None]
    ) -> OperationResult:
        if self.changed_externally():
            self.refresh()
            return OperationResult(
                False, "Configuration changed externally; it was reloaded. Review and retry."
            )
        original = self.config_path.read_text(encoding="utf-8")
        config = SambaConfig(original)
        try:
            mutate(config)
            proposed = config.render()
            if proposed == original:
                return OperationResult(True, "No changes were necessary")
            preflight = self.validator.syntax(proposed, self.config_path.parent)
            if not preflight.ok:
                return OperationResult(False, "Proposed configuration failed validation", preflight)
            backup = self.backups.create()
            atomic_write(self.config_path, proposed)
            postflight = self.validator.syntax(proposed, self.config_path.parent)
            if not postflight.ok:
                raise RuntimeError("testparm rejected the installed configuration")
            reloaded, detail = self.services.reload()
            if not reloaded:
                raise RuntimeError(detail)
            self.refresh()
            return OperationResult(
                True, f"{description} applied; backup: {backup.name}", postflight
            )
        except Exception as exc:
            try:
                atomic_write(self.config_path, original)
                self.services.reload()
                self.refresh()
            except Exception as rollback_exc:
                return OperationResult(
                    False, f"{description} failed ({exc}); rollback also failed: {rollback_exc}"
                )
            return OperationResult(False, f"{description} failed and was rolled back: {exc}")

    def restore(self, backup: Path) -> OperationResult:
        if backup.parent.resolve() != self.backups.directory.resolve() or not backup.is_file():
            return OperationResult(False, "Invalid backup path")
        content = backup.read_text(encoding="utf-8")
        return self.apply(
            f"Restore {backup.name}",
            lambda config: setattr(config, "lines", SambaConfig(content).lines),
        )
