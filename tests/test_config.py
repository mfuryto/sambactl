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


def test_fingerprint_changes(config_path: Path) -> None:
    before = file_fingerprint(config_path)
    config_path.write_text(config_path.read_text() + "# external\n")
    assert file_fingerprint(config_path) != before
