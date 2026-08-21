from __future__ import annotations

import pwd

from sambactl.models import OperationResult
from sambactl.samba.users import SambaUserManager
from sambactl.system.commands import CommandResult, CommandRunner
from sambactl.system.identity import validate_username


class LinuxUserManager:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def exists(self, username: str) -> bool:
        validate_username(username)
        try:
            pwd.getpwnam(username)
            return True
        except KeyError:
            return False

    def create(
        self, username: str, *, interactive: bool = False, create_home: bool = False
    ) -> CommandResult:
        validate_username(username)
        shell = "/bin/bash" if interactive else "/usr/sbin/nologin"
        home_option = "--create-home" if create_home else "--no-create-home"
        return self.runner.run(
            ("useradd", "--system", home_option, "--shell", shell, "--", username)
        )

    def delete(self, username: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(("userdel", "--", username))


class UserProvisioner:
    """Coordinate optional Linux-account creation with Samba-account creation."""

    def __init__(self, linux: LinuxUserManager, samba: SambaUserManager) -> None:
        self.linux = linux
        self.samba = samba

    def create(
        self, username: str, password: str, *, create_linux: bool, create_home: bool = False
    ) -> OperationResult:
        validate_username(username)
        existed = self.linux.exists(username)
        created_linux = False
        if not existed:
            if not create_linux:
                return OperationResult(False, "A corresponding Linux account is required")
            linux_result = self.linux.create(username, create_home=create_home)
            if not linux_result.ok:
                return OperationResult(
                    False, f"Linux account creation failed: {linux_result.stderr}"
                )
            created_linux = True

        try:
            samba_result = self.samba.create(username, password)
            if samba_result.ok:
                return OperationResult(True, "Samba user created")
            detail = self._safe_detail(samba_result, password)
        except Exception as exc:
            detail = self._redact(str(exc) or "unknown error", password)
        if created_linux:
            rollback = self.linux.delete(username)
            if not rollback.ok:
                rollback_detail = rollback.stderr.strip() or rollback.stdout.strip()
                return OperationResult(
                    False,
                    "CRITICAL: Samba account creation failed and the newly created Linux "
                    f"account could not be removed ({rollback_detail}). Manual intervention "
                    "required.",
                )
            return OperationResult(
                False, f"Samba account creation failed ({detail}); Linux account was rolled back"
            )
        return OperationResult(False, f"Samba account creation failed: {detail}")

    @staticmethod
    def _safe_detail(result: CommandResult, password: str) -> str:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return UserProvisioner._redact(detail, password)

    @staticmethod
    def _redact(detail: str, password: str) -> str:
        return detail.replace(password, "[REDACTED]") if password else detail
