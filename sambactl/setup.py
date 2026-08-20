from __future__ import annotations

import json
import os
from pathlib import Path

from sambactl.backup import BackupManager
from sambactl.models import RuntimeInfo
from sambactl.paths import backup_directory, detect_smb_conf
from sambactl.samba.service import SambaServiceManager
from sambactl.system.commands import CommandRunner

FEATURE_COMMANDS = {
    "configuration changes": ("testparm", "systemctl"),
    "Samba user enumeration": ("pdbedit",),
    "Samba user changes": ("smbpasswd",),
    "Linux user creation": ("useradd",),
    "Linux user deletion": ("userdel",),
}


def state_path() -> Path:
    override = os.environ.get("SAMBACTL_STATE_DIR")
    base = Path(override) if override else Path("/var/lib/sambactl")
    return base / "state.json"


def inspect_system(runner: CommandRunner, config_path: Path | None = None) -> RuntimeInfo:
    path = config_path or detect_smb_conf(runner)
    if not path.is_file() or not os.access(path, os.R_OK):
        raise PermissionError(f"Cannot read {path}")
    version = "Unknown"
    if runner.exists("smbd"):
        result = runner.run(("smbd", "--version"))
        if result.ok:
            version = result.stdout.strip()
    services = SambaServiceManager(runner).detect()
    commands = sorted({command for values in FEATURE_COMMANDS.values() for command in values})
    missing = [command for command in commands if not runner.exists(command)]
    capabilities = {
        feature: all(runner.exists(command) for command in commands)
        for feature, commands in FEATURE_COMMANDS.items()
    }
    if os.geteuid() == 0:
        BackupManager(path, backup_directory(path)).ensure_directory()
        try:
            target = state_path()
            target.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            target.write_text(
                json.dumps({"version": 1, "config": str(path)}) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
    service_manager = SambaServiceManager(runner)
    return RuntimeInfo(
        path,
        version,
        services,
        service_manager.mode(services),
        missing,
        capabilities,
    )
