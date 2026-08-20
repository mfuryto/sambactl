from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sambactl.models import Check, ShareFilesystemPlan, Status, ValidationReport
from sambactl.paths import backup_directory
from sambactl.samba.config import SambaConfig
from sambactl.samba.service import SambaServiceManager
from sambactl.samba.users import SambaUserManager
from sambactl.system.commands import CommandRunner
from sambactl.system.filesystem import resolved_regular_file
from sambactl.system.identity import lookup_group, lookup_user


class Validator:
    def __init__(self, runner: CommandRunner, services: SambaServiceManager) -> None:
        self.runner = runner
        self.services = services

    def syntax(self, text: str, directory: Path) -> ValidationReport:
        report = ValidationReport()
        if not self.runner.exists("testparm"):
            report.checks.append(Check("testparm", Status.FAILED, "Required command is missing"))
            return report
        temporary: Path | None = None
        try:
            fd, name = tempfile.mkstemp(prefix=".sambactl-validate-", dir=directory)
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            result = self.runner.run(("testparm", "-s", temporary.as_posix()))
            status = Status.READY if result.ok else Status.FAILED
            detail = "Configuration syntax is valid" if result.ok else result.stderr.strip()
            report.checks.append(Check("Configuration syntax", status, detail))
        except OSError as exc:
            report.checks.append(Check("Safe write", Status.FAILED, str(exc)))
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return report

    def dry_run(self, config_path: Path, proposed: str | None = None) -> ValidationReport:
        text = proposed if proposed is not None else config_path.read_text(encoding="utf-8")
        report = self.syntax(text, config_path.parent)
        for command in ("testparm", "systemctl"):
            available = self.runner.exists(command)
            report.checks.append(
                Check(
                    f"Required command: {command}",
                    Status.READY if available else Status.FAILED,
                    "available" if available else "missing",
                )
            )
        config = SambaConfig(text)
        for share in config.share_names():
            path_value = config.options(share).get("path")
            if not path_value:
                continue
            path = Path(path_value)
            if not path.exists():
                report.checks.append(
                    Check(f"Share [{share}] path", Status.WARNING, f"{path} does not exist")
                )
            elif not path.is_dir():
                report.checks.append(
                    Check(f"Share [{share}] path", Status.FAILED, f"{path} is not a directory")
                )
            elif not os.access(path, os.R_OK | os.X_OK):
                report.checks.append(
                    Check(f"Share [{share}] path", Status.WARNING, f"{path} is not accessible")
                )
        try:
            target = resolved_regular_file(config_path)
            writable = os.access(target, os.W_OK) and os.access(target.parent, os.W_OK)
        except OSError as exc:
            target = config_path
            writable = False
            report.checks.append(Check("Configuration target", Status.FAILED, str(exc)))
        report.checks.append(
            Check("Atomic write access", Status.READY if writable else Status.FAILED, str(target))
        )
        detected = self.services.detect()
        report.checks.append(
            Check(
                "Samba service",
                Status.READY if detected else Status.FAILED,
                f"{self.services.mode(detected)}: {', '.join(detected) or 'none'}",
            )
        )
        reloadable, reload_detail = self.services.can_reload()
        report.checks.append(
            Check("Reload capability", Status.READY if reloadable else Status.FAILED, reload_detail)
        )
        backup_path = backup_directory(config_path)
        backup_parent = backup_path if backup_path.exists() else backup_path.parent
        backup_writable = os.access(backup_parent, os.W_OK)
        report.checks.append(
            Check(
                "Backup directory",
                Status.READY if backup_writable else Status.FAILED,
                str(backup_path),
            )
        )
        return report

    def preflight_share(
        self,
        config_path: Path,
        proposed: str,
        filesystem: ShareFilesystemPlan,
        values: dict[str, str],
    ) -> ValidationReport:
        """Validate a proposed share and its filesystem/user dependencies without writes."""
        report = self.dry_run(config_path, proposed)
        report.checks.insert(0, Check("Proposed change", Status.READY, "Share configuration"))
        path = filesystem.path
        parent = next((p for p in (path, *path.parents) if p.exists()), None)
        if path.is_symlink():
            report.checks.append(
                Check("Target path", Status.FAILED, f"Refusing a symlinked share directory: {path}")
            )
        elif path.exists() and not path.is_dir():
            report.checks.append(Check("Target path", Status.FAILED, f"{path} is not a directory"))
        elif path.exists():
            report.checks.append(Check("Target path", Status.READY, f"Existing directory {path}"))
        elif parent and os.access(parent, os.W_OK | os.X_OK):
            report.checks.append(
                Check("Target path", Status.WARNING, f"{path} will be created below {parent}")
            )
        else:
            report.checks.append(Check("Target path", Status.FAILED, "No writable parent exists"))

        owner = lookup_user(filesystem.owner)
        group = lookup_group(filesystem.group)
        report.checks.append(
            Check(
                "Directory owner",
                Status.READY if owner else Status.FAILED,
                filesystem.owner if owner else f"Linux user {filesystem.owner} does not exist",
            )
        )
        report.checks.append(
            Check(
                "Directory group",
                Status.READY if group else Status.FAILED,
                filesystem.group if group else f"Linux group {filesystem.group} does not exist",
            )
        )
        mode_status = Status.WARNING if filesystem.mode & 0o002 else Status.READY
        report.checks.append(Check("Directory mode", mode_status, f"{filesystem.mode:04o}"))
        if path.exists() and owner and group:
            current = path.stat()
            actual_mode = current.st_mode & 0o7777
            if (current.st_uid, current.st_gid, actual_mode) != (
                owner.id,
                group.id,
                filesystem.mode,
            ):
                report.checks.append(
                    Check(
                        "Directory metadata change",
                        Status.WARNING,
                        f"Current uid:gid/mode {current.st_uid}:{current.st_gid}:{actual_mode:04o} "
                        f"will become {owner.id}:{group.id}:{filesystem.mode:04o}",
                    )
                )

        samba = SambaUserManager(self.runner)
        references_present = any(
            values.get(option, "").strip() for option in ("valid users", "write list")
        )
        if references_present:
            pdbedit_available = self.runner.exists("pdbedit")
            report.checks.append(
                Check(
                    "Required command: pdbedit",
                    Status.READY if pdbedit_available else Status.FAILED,
                    "available" if pdbedit_available else "needed to verify Samba users",
                )
            )
        for option in ("valid users", "write list"):
            for reference in values.get(option, "").replace(",", " ").split():
                try:
                    if reference.startswith("@"):
                        exists = lookup_group(reference[1:]) is not None
                        detail = f"group {reference[1:]}"
                    else:
                        linux_exists = lookup_user(reference) is not None
                        samba_exists = self.runner.exists("pdbedit") and samba.exists(reference)
                        exists = linux_exists and samba_exists
                        detail = f"Linux and Samba user {reference}"
                except ValueError:
                    exists = False
                    detail = f"invalid account reference {reference}"
                report.checks.append(
                    Check(
                        f"{option}: {reference}",
                        Status.READY if exists else Status.FAILED,
                        detail + (" exists" if exists else " is missing"),
                    )
                )
        return report
