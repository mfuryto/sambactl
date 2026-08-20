from pathlib import Path

from conftest import FakeRunner

from sambactl.models import Status
from sambactl.samba.service import SambaServiceManager
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
