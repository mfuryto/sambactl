from __future__ import annotations

import os
from pathlib import Path

from sambactl.paths import backup_directory, detect_smb_conf
from sambactl.samba.config import SambaConfig
from sambactl.samba.service import SambaServiceManager
from sambactl.samba.users import parse_pdbedit
from sambactl.setup import FEATURE_COMMANDS
from sambactl.system.commands import CommandRunner


def read_only_check(runner: CommandRunner, config_path: Path | None = None) -> tuple[bool, str]:
    """Inspect a real installation without creating files or changing system state."""
    path = config_path or detect_smb_conf(runner)
    text = path.read_text(encoding="utf-8")
    config = SambaConfig(text)
    version = "Unknown"
    if runner.exists("smbd"):
        result = runner.run(("smbd", "--version"))
        if result.ok:
            version = result.stdout.strip()

    syntax_ok = False
    syntax_detail = "testparm is missing"
    if runner.exists("testparm"):
        result = runner.run(("testparm", "-s", path.as_posix()))
        syntax_ok = result.ok
        syntax_detail = "valid" if result.ok else result.stderr.strip() or "invalid"

    service_manager = SambaServiceManager(runner)
    services = service_manager.detect()
    users: str
    if runner.exists("pdbedit"):
        result = runner.run(("pdbedit", "-L"))
        users = str(len(parse_pdbedit(result.stdout))) if result.ok else "unreadable"
    else:
        users = "unavailable (pdbedit missing)"

    dependencies = {
        feature: all(runner.exists(command) for command in commands)
        for feature, commands in FEATURE_COMMANDS.items()
    }
    backup_path = backup_directory(path)
    if backup_path.exists():
        backup_status = (
            "present, writable" if os.access(backup_path, os.W_OK) else "present, read-only"
        )
    else:
        backup_status = (
            f"not created; parent {'writable' if os.access(path.parent, os.W_OK) else 'read-only'}"
        )
    ready = syntax_ok and bool(services) and dependencies["configuration changes"]
    lines = [
        "Sambactl read-only host check",
        f"Configuration: {path}",
        f"Samba version: {version}",
        f"testparm: {syntax_detail}",
        f"Service mode: {service_manager.mode(services)}",
        f"Active services: {', '.join(services) or 'none'}",
        f"Shares: {len(config.share_names())}",
        f"Samba users: {users}",
        f"Backup directory: {backup_path} ({backup_status})",
        "Features:",
        *(
            f"  {feature}: {'available' if available else 'unavailable'}"
            for feature, available in dependencies.items()
        ),
        f"Administrative readiness: {'READY' if ready else 'NOT READY'}",
        "No files or accounts were modified.",
    ]
    return ready, "\n".join(lines)
