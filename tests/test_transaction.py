import os
from pathlib import Path

from conftest import FakeRunner

from sambactl.backup import BackupManager
from sambactl.models import Status
from sambactl.samba.service import SambaServiceManager
from sambactl.samba.validation import Validator
from sambactl.transaction import ConfigTransaction


class SequencedServices:
    def __init__(self, results):
        self.results = iter(results)
        self.reload_calls = 0

    def reload(self):
        self.reload_calls += 1
        return next(self.results)

    def can_reload(self):
        return True, "supported"


class NoReloadServices(SequencedServices):
    def can_reload(self):
        return False, "systemctl missing"


def make_transaction(
    config_path: Path, tmp_path: Path, runner: FakeRunner, services=None
) -> ConfigTransaction:
    services = services or SambaServiceManager(runner)
    return ConfigTransaction(
        config_path,
        BackupManager(config_path, tmp_path / "backups"),
        Validator(runner, services),
        services,
        lock_path=tmp_path / "lock",
    )


def test_transaction_applies_and_preserves_mode(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    result = transaction.apply(
        "Change workgroup", lambda c: c.set_options("global", {"workgroup": "NEW"})
    )
    assert result.ok
    assert "workgroup = NEW" in config_path.read_text()
    assert config_path.stat().st_mode & 0o777 == 0o640
    assert len(transaction.backups.list()) == 1


def test_backup_failure_writes_nothing_and_does_not_reload(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    original = config_path.read_text()
    monkeypatch.setattr(
        transaction.backups, "create", lambda: (_ for _ in ()).throw(OSError("full"))
    )
    monkeypatch.setattr(
        "sambactl.transaction.atomic_write",
        lambda *args: (_ for _ in ()).throw(AssertionError("write must not run")),
    )
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert not result.ok
    assert "Backup creation failed" in result.message
    assert config_path.read_text() == original
    assert services.reload_calls == 0


def test_initial_atomic_write_failure_is_rolled_back(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([(True, "rollback")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    original = config_path.read_text()
    real_write = __import__("sambactl.transaction", fromlist=["atomic_write"]).atomic_write
    calls = 0

    def fail_then_restore(path, content):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("install failed")
        real_write(path, content)

    monkeypatch.setattr("sambactl.transaction.atomic_write", fail_then_restore)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert "verified rollback succeeded" in result.message
    assert config_path.read_text() == original


def test_post_write_testparm_failure_is_rolled_back(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([(True, "rollback")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    original = config_path.read_text()
    syntax = transaction.validator.syntax
    calls = 0

    def fail_postflight(text, directory):
        nonlocal calls
        calls += 1
        report = syntax(text, directory)
        if calls == 2:
            report.checks[0].status = Status.FAILED
        return report

    monkeypatch.setattr(transaction.validator, "syntax", fail_postflight)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert "testparm rejected" in result.message
    assert "verified rollback succeeded" in result.message
    assert config_path.read_text() == original


def test_reload_capability_blocks_change_before_write(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    original = config_path.read_text()
    services = NoReloadServices([])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert not result.ok
    assert "cannot be applied safely" in result.message
    assert config_path.read_text() == original
    assert transaction.backups.list() == []


def test_non_root_change_is_refused(config_path: Path, tmp_path: Path, monkeypatch) -> None:
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert not result.ok
    assert "root privileges" in result.message


def test_lock_creation_failure_is_reported(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocked")
    transaction = ConfigTransaction(
        config_path,
        BackupManager(config_path, tmp_path / "backups"),
        Validator(FakeRunner(), SambaServiceManager(FakeRunner())),
        SambaServiceManager(FakeRunner()),
        lock_path=blocker / "lock",
    )
    result = transaction.apply("Change", lambda config: None)
    assert not result.ok
    assert "Could not lock configuration" in result.message


def test_mutation_error_and_noop_do_not_create_backup(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    failed = transaction.apply(
        "bad change", lambda config: (_ for _ in ()).throw(ValueError("bad value"))
    )
    noop = transaction.apply("noop", lambda config: None)
    assert not failed.ok and "Could not prepare" in failed.message
    assert noop.ok and "No changes" in noop.message
    assert transaction.backups.list() == []


def test_preflight_rejection_writes_nothing(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner(fail={"testparm"}))
    original = config_path.read_text()
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert not result.ok
    assert "failed validation" in result.message
    assert config_path.read_text() == original
    assert transaction.backups.list() == []


def test_initial_reload_failure_verified_rollback_succeeds(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    original = config_path.read_text()
    services = SequencedServices([(False, "initial failure"), (True, "rollback reload")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "BROKEN"}))
    assert not result.ok
    assert "verified rollback succeeded" in result.message
    assert config_path.read_text() == original


def test_initial_and_rollback_reload_fail(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([(False, "initial"), (False, "rollback")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "BROKEN"}))
    assert "CRITICAL" in result.message
    assert "Manual administrator intervention" in result.message


def test_restored_configuration_validation_failure(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    runner = FakeRunner()
    services = SequencedServices([(False, "initial")])
    transaction = make_transaction(config_path, tmp_path, runner, services)
    calls = 0
    original_syntax = transaction.validator.syntax

    def syntax(text, directory):
        nonlocal calls
        calls += 1
        report = original_syntax(text, directory)
        if calls == 3:
            report.checks[0].status = Status.FAILED
        return report

    monkeypatch.setattr(transaction.validator, "syntax", syntax)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert "CRITICAL" in result.message
    assert "validation" in result.message


def test_rollback_write_failure(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([(False, "initial")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    real_write = __import__("sambactl.transaction", fromlist=["atomic_write"]).atomic_write
    calls = 0

    def failing_second_write(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("restore write failed")
        real_write(path, content)

    monkeypatch.setattr("sambactl.transaction.atomic_write", failing_second_write)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert "CRITICAL" in result.message
    assert "atomic restore" in result.message


def test_success_refresh_failure_triggers_verified_rollback(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([(True, "initial"), (True, "rollback")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    original = config_path.read_text()
    refresh_calls = 0
    real_refresh = transaction.refresh

    def fail_once():
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls == 1:
            raise OSError("fingerprint failed")
        real_refresh()

    monkeypatch.setattr(transaction, "refresh", fail_once)
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert "verified rollback succeeded" in result.message
    assert config_path.read_text() == original


def test_rollback_fingerprint_refresh_failure_is_critical(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([(False, "initial"), (True, "rollback")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    monkeypatch.setattr(
        transaction, "refresh", lambda: (_ for _ in ()).throw(OSError("fingerprint failed"))
    )
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "X"}))
    assert "CRITICAL" in result.message
    assert "fingerprint refresh" in result.message


def test_external_change_is_detected(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    config_path.write_text(config_path.read_text() + "# outside\n")
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "NEW"}))
    assert not result.ok
    assert "externally" in result.message


def test_operation_after_external_refresh_uses_new_content(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    config_path.write_text(config_path.read_text() + "# external marker\n")
    rejected = transaction.apply("First", lambda c: c.set_options("global", {"workgroup": "A"}))
    applied = transaction.apply("Second", lambda c: c.set_options("global", {"workgroup": "B"}))
    assert not rejected.ok and applied.ok
    assert "# external marker" in config_path.read_text()


def test_restore_is_transactional(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    backup = transaction.backups.create()
    config_path.write_text(config_path.read_text().replace("OLD", "NEW"))
    transaction.refresh()
    result = transaction.restore(backup)
    assert result.ok
    assert "workgroup = OLD" in config_path.read_text()
    assert len(transaction.backups.list()) == 2


def test_invalid_backup_is_rejected_before_install(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    runner = FakeRunner(fail={"testparm"})
    transaction = make_transaction(config_path, tmp_path, runner)
    backup = transaction.backups.create()
    result = transaction.restore(backup)
    assert not result.ok
    assert "failed validation" in result.message


def test_backup_outside_managed_directory_is_rejected(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    outside = tmp_path / "outside.bak"
    outside.write_text(config_path.read_text())
    result = transaction.restore(outside)
    assert not result.ok
    assert result.message == "Invalid backup path"


def test_failed_restore_returns_to_pre_restore_configuration(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    services = SequencedServices([(True, "rollback")])
    transaction = make_transaction(config_path, tmp_path, FakeRunner(), services)
    backup = transaction.backups.create()
    config_path.write_text(config_path.read_text().replace("OLD", "CURRENT"))
    transaction.refresh()
    before_restore = config_path.read_text()
    syntax = transaction.validator.syntax
    calls = 0

    def reject_installed_backup(text, directory):
        nonlocal calls
        calls += 1
        report = syntax(text, directory)
        if calls == 3:
            report.checks[0].status = Status.FAILED
        return report

    monkeypatch.setattr(transaction.validator, "syntax", reject_installed_backup)
    result = transaction.restore(backup)
    assert not result.ok
    assert "verified rollback succeeded" in result.message
    assert config_path.read_text() == before_restore
