import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

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


def test_backups_are_never_more_permissive_than_source(config_path: Path, tmp_path: Path) -> None:
    os.chmod(config_path, 0o600)
    manager = BackupManager(config_path, tmp_path / "backups")
    automatic = manager.create()
    manual = manager.create_preserved("secure")
    assert automatic.stat().st_mode & 0o777 == 0o600
    assert manual.stat().st_mode & 0o777 == 0o600


def test_rotation_boundary_keeps_exact_retention_then_removes_oldest(
    config_path: Path, tmp_path: Path
) -> None:
    manager = BackupManager(config_path, tmp_path / "backups", retention=10)
    start = datetime(2026, 1, 1)
    first = manager.create(now=start)
    for offset in range(1, 10):
        manager.create(now=start + timedelta(seconds=offset))
    assert first.exists()
    assert len(manager.list()) == 10
    manager.create(now=start + timedelta(seconds=10))
    assert not first.exists()
    assert len(manager.list()) == 10


def test_old_manual_backup_is_never_rotated(config_path: Path, tmp_path: Path) -> None:
    manager = BackupManager(config_path, tmp_path / "backups", retention=1)
    manual = manager.create_preserved("forever")
    os.utime(manual, (1, 1))
    manager.create(now=datetime(2026, 1, 1))
    manager.create(now=datetime(2026, 1, 2))
    assert manual.exists()
    assert len([path for path in manager.list() if path.name.startswith("smb.conf.")]) == 1


def test_failed_copy_leaves_no_partial_backup(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    manager = BackupManager(config_path, tmp_path / "backups")

    def partial_copy(source, destination):
        Path(destination).write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr("sambactl.backup.shutil.copy2", partial_copy)
    with pytest.raises(OSError, match="disk full"):
        manager.create(now=datetime(2026, 1, 1))
    assert manager.list() == []
    assert list(manager.directory.iterdir()) == []


def test_manual_backup_rejects_empty_or_duplicate_name(config_path: Path, tmp_path: Path) -> None:
    manager = BackupManager(config_path, tmp_path / "backups")
    with pytest.raises(ValueError):
        manager.create_preserved("///")
    manager.create_preserved("keep")
    with pytest.raises(FileExistsError):
        manager.create_preserved("keep")


def test_existing_permissive_backup_directory_is_hardened(
    config_path: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o777)
    directory.chmod(0o777)
    BackupManager(config_path, directory).ensure_directory()
    assert directory.stat().st_mode & 0o777 == 0o700
