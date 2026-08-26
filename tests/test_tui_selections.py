from __future__ import annotations

from pathlib import Path

from sambactl.tui import app as app_module


def bare_app() -> app_module.SambactlApp:
    app = object.__new__(app_module.SambactlApp)
    app._refresh_latest = lambda: None
    return app


def test_empty_backup_list_has_safe_placeholder() -> None:
    assert app_module._backup_choices([]) == [("", "No backups available")]


def test_backup_entries_are_available_for_selection(tmp_path: Path) -> None:
    backup = tmp_path / "smb.conf.2026-08-21_09-00-00.bak"

    assert app_module._backup_choices([backup]) == [(str(backup), backup.name)]


def test_empty_share_templates_show_message(monkeypatch) -> None:
    app = bare_app()
    messages = []
    app._message = lambda title, text: messages.append((title, text))
    monkeypatch.setattr(app_module, "TEMPLATES", {})

    app._create_share()

    assert messages == [("New share", "No share templates are available.")]


def test_group_share_settings_apply_complete_access_policy() -> None:
    assert app_module._group_share_settings("editors") == {
        "read only": "no",
        "guest ok": "no",
        "valid users": "@editors",
        "force group": "editors",
        "create mask": "0660",
        "directory mask": "2770",
        "force create mode": "0660",
        "force directory mode": "2770",
    }


def test_share_list_label_summarizes_access_and_path() -> None:
    label = app_module._share_list_label(
        "projects",
        {
            "path": "/srv/samba/projects",
            "read only": "no",
            "guest ok": "no",
            "force group": "editors",
        },
    )

    assert "projects" in label
    assert "Read/write" in label
    assert "Group: editors" in label
    assert "/srv/samba/projects" in label
