import os
from pathlib import Path

from conftest import FakeRunner

from sambactl.setup import inspect_system


def test_dependencies_are_separated_by_feature(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    info = inspect_system(FakeRunner(fail={"useradd"}), config_path)
    assert info.capabilities["configuration changes"]
    assert not info.capabilities["Linux user creation"]
    assert info.capabilities["Samba user enumeration"]
    assert not (tmp_path / "backups").exists()
