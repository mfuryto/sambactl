from __future__ import annotations

from dataclasses import dataclass

from sambactl.system.commands import CommandResult, CommandRunner
from sambactl.system.identity import validate_username


@dataclass
class SambaUser:
    username: str
    uid: int | None = None
    disabled: bool = False


def parse_pdbedit(output: str) -> list[SambaUser]:
    if "Unix username:" in output:
        return _parse_verbose_pdbedit(output)

    users = []
    for line in output.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0]:
            try:
                uid = int(parts[1])
            except ValueError:
                uid = None
            users.append(SambaUser(parts[0], uid))
    return users


def _parse_verbose_pdbedit(output: str) -> list[SambaUser]:
    """Parse ``pdbedit -L -v`` without requesting password hashes."""
    users: list[SambaUser] = []
    current: dict[str, str] = {}

    def append_current() -> None:
        username = current.get("Unix username")
        if not username:
            return
        try:
            uid = int(current.get("Unix user ID", ""))
        except ValueError:
            uid = None
        flags = current.get("Account Flags", "")
        users.append(SambaUser(username, uid, disabled="D" in flags.strip("[] ")))

    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key == "Unix username" and current:
            append_current()
            current = {}
        current[key] = value
    append_current()
    return users


class SambaUserManager:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def list(self) -> list[SambaUser]:
        # Deliberately omit -w: that mode emits password hashes.
        result = self.runner.run(("pdbedit", "-L", "-v"))
        return parse_pdbedit(result.stdout) if result.ok else []

    def exists(self, username: str) -> bool:
        validate_username(username)
        return self.runner.run(("pdbedit", "-L", "-u", username)).ok

    def create(self, username: str, password: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(
            ("smbpasswd", "-s", "-a", username), input_text=f"{password}\n{password}\n"
        )

    def change_password(self, username: str, password: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(
            ("smbpasswd", "-s", username), input_text=f"{password}\n{password}\n"
        )

    def enable(self, username: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(("smbpasswd", "-e", username))

    def disable(self, username: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(("smbpasswd", "-d", username))

    def delete(self, username: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(("smbpasswd", "-x", username))

    def status(self, username: str) -> CommandResult:
        validate_username(username)
        return self.runner.run(("pdbedit", "-Lv", "-u", username))
