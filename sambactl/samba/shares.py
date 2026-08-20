from __future__ import annotations

from collections.abc import Mapping

from sambactl.samba.config import SambaConfig


def validate_share_name(name: str) -> str:
    if (
        not name
        or name != name.strip()
        or name.casefold() == "global"
        or any(ord(character) < 32 for character in name)
        or "[" in name
        or "]" in name
    ):
        raise ValueError("Share name is empty, reserved, or contains section/control characters")
    return name


TEMPLATES: dict[str, dict[str, str]] = {
    "Private Share": {
        "browseable": "yes",
        "read only": "no",
        "guest ok": "no",
        "create mask": "0660",
        "directory mask": "0770",
    },
    "Group Share": {
        "browseable": "yes",
        "read only": "no",
        "guest ok": "no",
        "create mask": "0660",
        "directory mask": "2770",
    },
    "Public Read Only": {"browseable": "yes", "read only": "yes", "guest ok": "yes"},
    "Public Read/Write": {
        "browseable": "yes",
        "read only": "no",
        "guest ok": "yes",
        "create mask": "0664",
        "directory mask": "0775",
    },
    "Custom": {},
}


class ShareManager:
    @staticmethod
    def create(config: SambaConfig, name: str, values: Mapping[str, str]) -> None:
        validate_share_name(name)
        if config.section(name):
            raise ValueError(f"Share [{name}] already exists")
        config.set_options(name, values)

    @staticmethod
    def update(
        config: SambaConfig,
        name: str,
        values: Mapping[str, str | None],
        new_name: str | None = None,
    ) -> None:
        if not config.section(name):
            raise KeyError(name)
        if new_name and new_name != name:
            validate_share_name(new_name)
            config.rename_section(name, new_name)
            name = new_name
        config.set_options(name, values)

    @staticmethod
    def delete(config: SambaConfig, name: str) -> None:
        config.delete_section(name)
