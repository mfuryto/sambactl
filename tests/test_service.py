from sambactl.samba.service import SambaServiceManager
from sambactl.system.commands import CommandResult


class UnitRunner:
    def __init__(self, active, *, can_reload=True, reload_fail=()):
        self.active_units = set(active)
        self.reload_supported = can_reload
        self.reload_fail = set(reload_fail)
        self.calls = []

    def exists(self, command):
        return command == "systemctl"

    def run(self, args, **kwargs):
        args = tuple(args)
        self.calls.append(args)
        if args[1] == "is-active":
            return CommandResult(args, 0 if args[-1] in self.active_units else 3)
        if args[1] == "show":
            return CommandResult(args, 0, "yes\n" if self.reload_supported else "no\n")
        if args[1] == "reload" and args[-1] in self.reload_fail:
            return CommandResult(args, 1, stderr="reload denied")
        return CommandResult(args, 0)


def test_prefers_active_smbd_over_inactive_installed_units() -> None:
    manager = SambaServiceManager(UnitRunner({"smbd.service"}))
    assert manager.detect() == ["smbd.service"]
    assert "Standalone" in manager.mode()


def test_ad_dc_layout_wins_if_active() -> None:
    manager = SambaServiceManager(UnitRunner({"smbd.service", "samba-ad-dc.service"}))
    assert manager.detect() == ["samba-ad-dc.service"]
    assert "Active Directory" in manager.mode()


def test_samba_service_layout() -> None:
    manager = SambaServiceManager(UnitRunner({"samba.service"}))
    assert manager.detect() == ["samba.service"]


def test_no_active_service_is_not_reloaded() -> None:
    runner = UnitRunner(set())
    manager = SambaServiceManager(runner)
    ok, _ = manager.reload()
    assert not ok
    assert not any(call[1] == "reload" for call in runner.calls)


def test_missing_systemctl_has_no_layout() -> None:
    runner = UnitRunner(set())
    runner.exists = lambda command: False
    manager = SambaServiceManager(runner)
    assert manager.detect() == []
    assert manager.mode() == "No active Samba service"


def test_active_service_without_reload_capability_is_rejected() -> None:
    manager = SambaServiceManager(UnitRunner({"smbd.service"}, can_reload=False))
    ok, detail = manager.can_reload()
    assert not ok
    assert "does not report reload support" in detail


def test_reload_failure_is_reported() -> None:
    manager = SambaServiceManager(UnitRunner({"smbd.service"}, reload_fail={"smbd.service"}))
    ok, detail = manager.reload()
    assert not ok
    assert "reload denied" in detail


def test_reload_success_reports_target() -> None:
    manager = SambaServiceManager(UnitRunner({"smbd.service"}))
    ok, detail = manager.reload()
    assert ok
    assert "smbd.service" in detail
