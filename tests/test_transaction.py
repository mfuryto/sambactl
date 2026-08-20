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

    def reload(self):
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
