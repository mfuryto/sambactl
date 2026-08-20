from datetime import datetime, timedelta
from pathlib import Path

from sambactl.backup import BackupManager


def test_rotation_keeps_ten_and_manual(config_path: Path, tmp_path: Path) -> None:
    manager = BackupManager(config_path, tmp_path / "backups", retention=10)
    start = datetime(2026, 1, 1)
    for offset in range(12):
        manager.create(now=start + timedelta(seconds=offset))
    manual = manager.create_preserved("release-candidate")
    assert len([p for p in manager.list() if not p.name.startswith("manual-")]) == 10
    assert manual.exists()


def test_preserved_names_are_safe(config_path: Path, tmp_path: Path) -> None:
    manager = BackupManager(config_path, tmp_path / "backups")
    created = manager.create_preserved("nightly / safe")
    assert created.parent == tmp_path / "backups"
    assert created.name == "manual-nightly-safe.bak"
