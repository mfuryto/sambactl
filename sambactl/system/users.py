from __future__ import annotations

import pwd

from sambactl.system.commands import CommandResult, CommandRunner


class LinuxUserManager:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def exists(self, username: str) -> bool:
        try:
            pwd.getpwnam(username)
            return True
        except KeyError:
            return False

    def create(self, username: str, *, interactive: bool = False) -> CommandResult:
        shell = "/bin/bash" if interactive else "/usr/sbin/nologin"
        return self.runner.run(
            ("useradd", "--system", "--no-create-home", "--shell", shell, username)
        )

    def delete(self, username: str) -> CommandResult:
        return self.runner.run(("userdel", username))
