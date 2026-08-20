from pathlib import Path

from conftest import FakeRunner

from sambactl.models import ShareFilesystemPlan, Status
from sambactl.samba.config import SambaConfig
from sambactl.samba.service import SambaServiceManager
from sambactl.samba.shares import ShareManager
from sambactl.samba.validation import Validator


def test_validation_success(config_path: Path) -> None:
    runner = FakeRunner()
    report = Validator(runner, SambaServiceManager(runner)).syntax(
        config_path.read_text(), config_path.parent
    )
    assert report.status == Status.READY


def test_missing_testparm_fails(config_path: Path) -> None:
    runner = FakeRunner(fail={"testparm"})
    report = Validator(runner, SambaServiceManager(runner)).syntax(
        config_path.read_text(), config_path.parent
    )
    assert report.status == Status.FAILED


def test_dry_run_reports_missing_share_path(config_path: Path) -> None:
    runner = FakeRunner()
    report = Validator(runner, SambaServiceManager(runner)).dry_run(config_path)
    assert report.status == Status.WARNING
    assert any("does not exist" in check.detail for check in report.checks)


def test_share_operation_preflight_checks_filesystem_and_identities(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    validator = Validator(runner, SambaServiceManager(runner))
    proposed = SambaConfig.read(config_path)
    share_path = tmp_path / "new-share"
    values = {"path": str(share_path), "valid users": "alice", "write list": "@editors"}
    ShareManager.create(proposed, "new", values)
    identity = type("Identity", (), {"id": 1000})()
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: identity)
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: identity)

    report = validator.preflight_share(
        config_path,
        proposed.render(),
        ShareFilesystemPlan(share_path, "alice", "editors", 0o2770),
        values,
    )

    assert report.ok
    assert not share_path.exists()
    names = {check.name for check in report.checks}
    assert {"Directory owner", "Directory group", "Directory mode"} <= names
    assert "valid users: alice" in names
    assert "write list: @editors" in names


def test_share_preflight_rejects_missing_group(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    validator = Validator(runner, SambaServiceManager(runner))
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: object())
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: None)
    report = validator.preflight_share(
        config_path,
        config_path.read_text(),
        ShareFilesystemPlan(tmp_path / "share", "alice", "missing", 0o2770),
        {"path": str(tmp_path / "share")},
    )
    assert report.status == Status.FAILED
    assert any(check.name == "Directory group" for check in report.checks)
