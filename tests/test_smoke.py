from pathlib import Path

from conftest import FakeRunner

from sambactl.smoke import read_only_check


def test_read_only_check_reports_without_writes(config_path: Path, tmp_path: Path) -> None:
    before = {path.name for path in tmp_path.iterdir()}
    ready, output = read_only_check(FakeRunner(), config_path)
    after = {path.name for path in tmp_path.iterdir()}
    assert ready
    assert before == after
    assert f"Configuration: {config_path}" in output
    assert "Shares: 1" in output
    assert "No files or accounts were modified" in output


def test_read_only_check_fails_readiness_without_testparm(config_path: Path) -> None:
    ready, output = read_only_check(FakeRunner(fail={"testparm"}), config_path)
    assert not ready
    assert "testparm is missing" in output
