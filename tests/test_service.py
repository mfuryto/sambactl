from sambactl.samba.service import SambaServiceManager
from sambactl.system.commands import CommandResult


class UnitRunner:
    def __init__(self, active):
        self.active_units = set(active)
        self.calls = []

    def exists(self, command):
        return command == "systemctl"

    def run(self, args, **kwargs):
        args = tuple(args)
        self.calls.append(args)
        if args[1] == "is-active":
            return CommandResult(args, 0 if args[-1] in self.active_units else 3)
        if args[1] == "show":
            return CommandResult(args, 0, "yes\n")
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
