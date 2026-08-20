from __future__ import annotations

from sambactl.system.commands import CommandRunner


class SambaServiceManager:
    CANDIDATES = ("smbd.service", "samba.service", "samba-ad-dc.service")

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def detect(self) -> list[str]:
        """Return only the active unit(s) for the detected Samba layout."""
        if not self.runner.exists("systemctl"):
            return []
        active = [service for service in self.CANDIDATES if self.active(service)]
        if "samba-ad-dc.service" in active:
            return ["samba-ad-dc.service"]
        if "smbd.service" in active:
            return ["smbd.service"]
        if "samba.service" in active:
            return ["samba.service"]
        return []

    def mode(self, services: list[str] | None = None) -> str:
        targets = services if services is not None else self.detect()
        if "samba-ad-dc.service" in targets:
            return "Active Directory domain controller"
        if "smbd.service" in targets:
            return "Standalone/member server (smbd)"
        if "samba.service" in targets:
            return "Samba service"
        return "No active Samba service"

    def reload(self, services: list[str] | None = None) -> tuple[bool, str]:
        targets = services if services is not None else self.detect()
        if not targets:
            return False, "No reloadable Samba service was detected"
        failures = []
        for service in targets:
            result = self.runner.run(("systemctl", "reload", service))
            if not result.ok:
                failures.append(f"{service}: {result.stderr.strip() or result.stdout.strip()}")
        return (not failures, "; ".join(failures) if failures else f"Reloaded {', '.join(targets)}")

    def can_reload(self) -> tuple[bool, str]:
        targets = self.detect()
        if not targets:
            return False, "No active Samba service detected"
        for service in targets:
            result = self.runner.run(
                ("systemctl", "show", service, "--property=CanReload", "--value")
            )
            if not result.ok or result.stdout.strip().casefold() != "yes":
                return False, f"{service} does not report reload support"
        return True, f"Reload supported by {', '.join(targets)}"

    def active(self, service: str) -> bool:
        return self.runner.run(("systemctl", "is-active", "--quiet", service)).ok
