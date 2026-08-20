import os
from pathlib import Path

from sambactl.system.filesystem import atomic_write, set_directory_metadata


def test_atomic_write_preserves_symlink_and_target_metadata(tmp_path: Path) -> None:
    target = tmp_path / "real.conf"
    target.write_text("old\n")
    target.chmod(0o640)
    link = tmp_path / "smb.conf"
    link.symlink_to(target.name)

    atomic_write(link, "new\n")

    assert link.is_symlink()
    assert target.read_text() == "new\n"
    assert target.stat().st_mode & 0o777 == 0o640


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
