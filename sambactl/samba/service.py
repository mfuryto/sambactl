from __future__ import annotations

from sambactl.system.commands import CommandRunner


class SambaServiceManager:
    CANDIDATES = ("smbd.service", "samba.service", "samba-ad-dc.service")

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def detect(self) -> list[str]:
        if not self.runner.exists("systemctl"):
            return []
        services = []
        for service in self.CANDIDATES:
            result = self.runner.run(
                ("systemctl", "show", service, "--property=LoadState", "--value")
            )
            if result.ok and result.stdout.strip() == "loaded":
                services.append(service)
        return services

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

    def active(self, service: str) -> bool:
        return self.runner.run(("systemctl", "is-active", "--quiet", service)).ok
