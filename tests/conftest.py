from __future__ import annotations

import os
from pathlib import Path

import pytest

from sambactl.system.commands import CommandResult

SAMPLE = """# Site configuration
[global]
    workgroup = OLD
    fruit:metadata = stream

[docs]
    path = /srv/docs
    read only = yes
    custom option = keep me
"""


class FakeRunner:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[tuple[str, ...]] = []

    def exists(self, command: str) -> bool:
        return command not in self.fail

    def run(self, args, **kwargs) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        failed = argv[0] in self.fail or "reload" in self.fail and "reload" in argv
        if argv[:2] == ("systemctl", "show"):
            return CommandResult(argv, 0, "yes\n", "")
        return CommandResult(
            argv, 1 if failed else 0, "" if failed else "ok\n", "failure" if failed else ""
        )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "smb.conf"
    path.write_text(SAMPLE, encoding="utf-8")
    os.chmod(path, 0o640)
    return path
