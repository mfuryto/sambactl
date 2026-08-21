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
