import os
from pathlib import Path

import pytest

from sambactl.system.filesystem import (
    atomic_write,
    directory_metadata,
    safe_create_directory,
    set_directory_metadata,
)


def test_atomic_write_preserves_symlink_and_target_metadata(tmp_path: Path) -> None:
    target = tmp_path / "real.conf"
    target.write_text("old\n")
    target.chmod(0o2640)
    before = target.stat()
    link = tmp_path / "smb.conf"
    link.symlink_to(target.name)

    atomic_write(link, "new\n")

    assert link.is_symlink()
    assert target.read_text() == "new\n"
    after = target.stat()
    assert after.st_mode & 0o7777 == 0o2640
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)


def test_broken_symlink_is_rejected(tmp_path: Path) -> None:
    link = tmp_path / "smb.conf"
    link.symlink_to("missing.conf")
    try:
        atomic_write(link, "new")
    except OSError as exc:
        assert "broken" in str(exc).lower() or "unsafe" in str(exc).lower()
    else:
        raise AssertionError("broken symlink was accepted")


def test_extended_attribute_is_preserved_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "smb.conf"
    target.write_text("old")
    try:
        os.setxattr(target, "user.sambactl-test", b"kept")
    except OSError:
        return
    atomic_write(target, "new")
    assert os.getxattr(target, "user.sambactl-test") == b"kept"


def test_directory_metadata_and_symlink_refusal(tmp_path: Path) -> None:
    directory = tmp_path / "share"
    directory.mkdir()
    current = directory.stat()
    set_directory_metadata(directory, current.st_uid, current.st_gid, 0o2770)
    assert directory.stat().st_mode & 0o7777 == 0o2770
    link = tmp_path / "share-link"
    link.symlink_to(directory, target_is_directory=True)
    try:
        set_directory_metadata(link, current.st_uid, current.st_gid, 0o2770)
    except OSError as exc:
        assert "Refusing" in str(exc)
    else:
        raise AssertionError("directory symlink was accepted")


def test_temporary_file_is_removed_when_xattr_copy_fails(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "smb.conf"
    target.write_text("old")
    monkeypatch.setattr(
        "sambactl.system.filesystem._copy_xattrs",
        lambda *args: (_ for _ in ()).throw(OSError("xattr failed")),
    )
    with pytest.raises(OSError, match="xattr failed"):
        atomic_write(target, "new")
    assert target.read_text() == "old"
    assert list(tmp_path.glob(".smb.conf.*")) == []


def test_temporary_file_is_removed_when_replace_fails(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "smb.conf"
    target.write_text("old")
    monkeypatch.setattr(
        "sambactl.system.filesystem.os.replace",
        lambda *args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        atomic_write(target, "new")
    assert target.read_text() == "old"
    assert list(tmp_path.glob(".smb.conf.*")) == []


def test_directory_metadata_can_be_captured_and_rolled_back(tmp_path: Path) -> None:
    directory = tmp_path / "share"
    directory.mkdir(mode=0o750)
    original = directory_metadata(directory)
    set_directory_metadata(directory, original[0], original[1], 0o2770)
    assert directory_metadata(directory)[2] == 0o2770
    set_directory_metadata(directory, *original)
    assert directory_metadata(directory) == original


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_safe_create_directory_refuses_unsafe_existing_target(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "share"
    if kind == "file":
        target.write_text("data")
    else:
        real = tmp_path / "real"
        real.mkdir()
        target.symlink_to(real, target_is_directory=True)
    current = tmp_path.stat()
    with pytest.raises(OSError):
        safe_create_directory(target, current.st_uid, current.st_gid, 0o2770)


def test_atomic_write_rejects_directory_target(tmp_path: Path) -> None:
    target = tmp_path / "smb.conf"
    target.mkdir()
    with pytest.raises(OSError, match="not a regular file"):
        atomic_write(target, "new")


def test_directory_metadata_refuses_regular_file(tmp_path: Path) -> None:
    target = tmp_path / "share"
    target.write_text("not a directory")
    with pytest.raises(OSError, match="Refusing"):
        directory_metadata(target)


def test_xattr_set_failure_preserves_original_and_cleans_temp(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "smb.conf"
    target.write_text("old")
    monkeypatch.setattr(os, "listxattr", lambda path: ["user.test"])
    monkeypatch.setattr(os, "getxattr", lambda path, name: b"value")
    monkeypatch.setattr(
        os, "setxattr", lambda *args: (_ for _ in ()).throw(OSError("not supported"))
    )
    with pytest.raises(OSError, match="extended attribute"):
        atomic_write(target, "new")
    assert target.read_text() == "old"
    assert list(tmp_path.glob(".smb.conf.*")) == []


def test_non_root_chown_permission_error_is_tolerated(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "smb.conf"
    target.write_text("old")
    monkeypatch.setattr(os, "chown", lambda *args: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    atomic_write(target, "new")
    assert target.read_text() == "new"


def test_root_chown_permission_error_aborts_and_cleans_temp(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "smb.conf"
    target.write_text("old")
    monkeypatch.setattr(os, "chown", lambda *args: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(PermissionError):
        atomic_write(target, "new")
    assert target.read_text() == "old"
    assert list(tmp_path.glob(".smb.conf.*")) == []


def test_nonempty_directory_removal_refuses_data(tmp_path: Path) -> None:
    from sambactl.system.filesystem import remove_empty_directory

    directory = tmp_path / "share"
    directory.mkdir()
    data = directory / "keep"
    data.write_text("important")
    with pytest.raises(OSError):
        remove_empty_directory(directory)
    assert data.read_text() == "important"
