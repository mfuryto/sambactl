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

    def create(self, username: str, *, interactive: bool = False) -> CommandResult:
        validate_username(username)
        shell = "/bin/bash" if interactive else "/usr/sbin/nologin"
        return self.runner.run(
            ("useradd", "--system", "--no-create-home", "--shell", shell, "--", username)
        )

    def delete(self, username: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(("userdel", "--", username))


class UserProvisioner:
    """Coordinate optional Linux-account creation with Samba-account creation."""

    def __init__(self, linux: LinuxUserManager, samba: SambaUserManager) -> None:
        self.linux = linux
        self.samba = samba

    def create(self, username: str, password: str, *, create_linux: bool) -> OperationResult:
        validate_username(username)
        existed = self.linux.exists(username)
        created_linux = False
        if not existed:
            if not create_linux:
                return OperationResult(False, "A corresponding Linux account is required")
            linux_result = self.linux.create(username)
            if not linux_result.ok:
                return OperationResult(
                    False, f"Linux account creation failed: {linux_result.stderr}"
                )
            created_linux = True

        samba_result = self.samba.create(username, password)
        if samba_result.ok:
            return OperationResult(True, "Samba user created")
        detail = samba_result.stderr.strip() or samba_result.stdout.strip() or "unknown error"
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
