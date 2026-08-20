from pathlib import Path

import pytest

from sambactl.samba.config import SambaConfig, file_fingerprint
from sambactl.samba.shares import ShareManager


def test_parses_sections_and_options_preserving_unknown(config_path: Path) -> None:
    config = SambaConfig.read(config_path)
    assert config.share_names() == ["docs"]
    config.set_options("docs", {"read only": "no"})
    rendered = config.render()
    assert "# Site configuration" in rendered
    assert "custom option = keep me" in rendered
    assert "fruit:metadata = stream" in rendered
    assert "read only = no" in rendered


def test_share_create_modify_delete(config_path: Path) -> None:
    config = SambaConfig.read(config_path)
    ShareManager.create(config, "media", {"path": "/srv/media", "guest ok": "no"})
    assert config.options("media")["path"] == "/srv/media"
    ShareManager.update(config, "media", {"comment": "Media"}, new_name="videos")
    assert "videos" in config.share_names()
    assert config.options("videos")["comment"] == "Media"
    ShareManager.delete(config, "videos")
    assert config.share_names() == ["docs"]


def test_duplicate_share_rejected(config_path: Path) -> None:
    with pytest.raises(ValueError):
        ShareManager.create(SambaConfig.read(config_path), "docs", {})


@pytest.mark.parametrize("name", ["", "global", " bad", "bad]name", "bad\nname"])
def test_invalid_share_names_are_rejected(config_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        ShareManager.create(SambaConfig.read(config_path), name, {"path": "/srv/test"})


def test_rename_preserves_unrelated_configuration(config_path: Path) -> None:
    config = SambaConfig.read(config_path)
    ShareManager.update(config, "docs", {"comment": "Renamed"}, new_name="documents")
    rendered = config.render()
    assert "[documents]" in rendered
    assert "custom option = keep me" in rendered
    assert "fruit:metadata = stream" in rendered


def test_fingerprint_changes(config_path: Path) -> None:
    before = file_fingerprint(config_path)
    config_path.write_text(config_path.read_text() + "# external\n")
    assert file_fingerprint(config_path) != before


COMPLEX = """# header comment

[global] ; inline section comment
\tworkgroup=OLD
    unknown:global = preserve this
    workgroup   =   LAST

; share comment
[odd share]
 path=/srv/odd
 read only=yes
    read only = no
 custom:option = untouched

[custom-module]
    magic option = yes
# final comment
"""


def test_duplicate_managed_options_are_all_updated_and_format_is_preserved() -> None:
    config = SambaConfig(COMPLEX)
    config.set_options("global", {"workgroup": "NEW"})
    config.set_options("odd share", {"read only": "yes"})
    rendered = config.render()
    assert "\tworkgroup=NEW\n" in rendered
    assert "    workgroup   =   NEW\n" in rendered
    assert " read only=yes\n" in rendered
    assert "    read only = yes\n" in rendered
    assert "unknown:global = preserve this" in rendered
    assert "custom:option = untouched" in rendered
    assert "[custom-module]\n    magic option = yes\n# final comment\n" in rendered


def test_add_and_delete_leave_unrelated_text_byte_for_byte() -> None:
    config = SambaConfig(COMPLEX)
    original_custom = "[custom-module]\n    magic option = yes\n# final comment\n"
    ShareManager.create(config, "new", {"path": "/srv/new"})
    assert COMPLEX in config.render()
    ShareManager.delete(config, "new")
    rendered = config.render()
    assert rendered == COMPLEX
    assert original_custom in rendered


def test_removing_duplicate_option_removes_every_effective_occurrence() -> None:
    config = SambaConfig(COMPLEX)
    config.set_options("global", {"workgroup": None})
    rendered = config.render()
    assert "workgroup" not in rendered
    assert "# header comment\n\n[global] ; inline section comment\n" in rendered
    assert "unknown:global = preserve this" in rendered
