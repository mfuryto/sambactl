from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sambactl.models import Check, Status, ValidationReport
from sambactl.samba.config import SambaConfig
from sambactl.samba.service import SambaServiceManager
from sambactl.system.commands import CommandRunner


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
        writable = os.access(config_path, os.W_OK) and os.access(config_path.parent, os.W_OK)
        report.checks.append(
            Check(
                "Atomic write access", Status.READY if writable else Status.FAILED, str(config_path)
            )
        )
        detected = self.services.detect()
        report.checks.append(
            Check(
                "Samba service",
                Status.READY if detected else Status.FAILED,
                ", ".join(detected) or "None detected",
            )
        )
        return report
