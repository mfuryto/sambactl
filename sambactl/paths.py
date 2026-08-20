from __future__ import annotations

import os
from pathlib import Path

from sambactl.system.commands import CommandRunner


def detect_smb_conf(runner: CommandRunner) -> Path:
    override = os.environ.get("SAMBACTL_CONFIG")
    if override:
        return Path(override).resolve()
    if runner.exists("smbd"):
        result = runner.run(("smbd", "-b"))
        for line in result.stdout.splitlines():
            if "CONFIGFILE" in line:
                candidate = line.split()[-1]
                if Path(candidate).is_file():
                    return Path(candidate)
    for candidate in (Path("/etc/samba/smb.conf"), Path("/usr/local/etc/smb.conf")):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No smb.conf found; set SAMBACTL_CONFIG to its path")


def backup_directory(config_path: Path) -> Path:
    return config_path.parent / "backups"
