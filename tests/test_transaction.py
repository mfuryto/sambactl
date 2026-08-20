import os
from pathlib import Path

from conftest import FakeRunner

from sambactl.backup import BackupManager
from sambactl.samba.service import SambaServiceManager
from sambactl.samba.validation import Validator
from sambactl.transaction import ConfigTransaction


def make_transaction(config_path: Path, tmp_path: Path, runner: FakeRunner) -> ConfigTransaction:
    services = SambaServiceManager(runner)
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


def test_reload_failure_rolls_back(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    original = config_path.read_text()
    transaction = make_transaction(config_path, tmp_path, FakeRunner(fail={"reload"}))
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "BROKEN"}))
    assert not result.ok
    assert config_path.read_text() == original


def test_external_change_is_detected(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    config_path.write_text(config_path.read_text() + "# outside\n")
    result = transaction.apply("Change", lambda c: c.set_options("global", {"workgroup": "NEW"}))
    assert not result.ok
    assert "externally" in result.message


def test_restore_is_transactional(monkeypatch, config_path: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    transaction = make_transaction(config_path, tmp_path, FakeRunner())
    backup = transaction.backups.create()
    config_path.write_text(config_path.read_text().replace("OLD", "NEW"))
    transaction.refresh()
    result = transaction.restore(backup)
    assert result.ok
    assert "workgroup = OLD" in config_path.read_text()
