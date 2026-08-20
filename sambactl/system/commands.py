from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    """Single mockable boundary for external programs. Password input uses stdin only."""

    def exists(self, command: str) -> bool:
        return shutil.which(command) is not None

    def run(
        self, args: Iterable[str], *, input_text: str | None = None, timeout: int = 30
    ) -> CommandResult:
        argv = tuple(args)
        try:
            completed = subprocess.run(
                argv,
                input=input_text,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(argv, 127, "", str(exc))
