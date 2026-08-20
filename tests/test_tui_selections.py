from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sambactl.samba.users import SambaUser
from sambactl.tui import app as app_module


class Dialog:
    def __init__(self, result) -> None:
        self.result = result

    def run(self):
        return self.result


def bare_app() -> app_module.SambactlApp:
    app = object.__new__(app_module.SambactlApp)
    app._refresh_latest = lambda: None
    return app


def test_empty_backup_list_shows_message_without_radio_dialog(monkeypatch) -> None:
    app = bare_app()
    app.backups = SimpleNamespace(list=lambda: [])
    messages = []
    app._message = lambda title, text: messages.append((title, text))
    monkeypatch.setattr(app_module, "button_dialog", lambda **kwargs: Dialog("restore"))
    monkeypatch.setattr(
        app_module,
        "radiolist_dialog",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("radio list must not open")),
    )

    app._backups_menu()

    assert messages == [("Restore", "No backups are available yet.")]


def test_backup_list_with_entries_keeps_selection_behavior(monkeypatch, tmp_path: Path) -> None:
    app = bare_app()
    backup = tmp_path / "smb.conf.2026-08-21_09-00-00.bak"
    app.backups = SimpleNamespace(list=lambda: [backup])
    app._message = lambda *args: None
    selected_values = []
    monkeypatch.setattr(app_module, "button_dialog", lambda **kwargs: Dialog("restore"))

    def radio_dialog(**kwargs):
        selected_values.extend(kwargs["values"])
        return Dialog(str(backup))

    monkeypatch.setattr(app_module, "radiolist_dialog", radio_dialog)
    monkeypatch.setattr(app_module, "confirm", lambda *args, **kwargs: False)

    app._backups_menu()

    assert selected_values == [(str(backup), backup.name)]


def test_no_samba_users_shows_message_without_radio_dialog(monkeypatch) -> None:
    app = bare_app()
    app.runner = SimpleNamespace(exists=lambda command: True)
    app.samba_users = SimpleNamespace(list=lambda: [])
    messages = []
    app._message = lambda title, text: messages.append((title, text))
    actions = iter(("password", None))
    monkeypatch.setattr(app_module, "button_dialog", lambda **kwargs: Dialog(next(actions)))
    monkeypatch.setattr(
        app_module,
        "radiolist_dialog",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("radio list must not open")),
    )

    app._users_menu()

    assert messages == [("Select Samba user", "No Samba users are available.")]


def test_samba_users_are_passed_to_selection_dialog(monkeypatch) -> None:
    app = bare_app()
    app.runner = SimpleNamespace(exists=lambda command: True)
    app.samba_users = SimpleNamespace(list=lambda: [SambaUser("alice", 1001)])
    app._linux_account_label = lambda username: "present"
    actions = iter(("status", None))
    selected_values = []
    monkeypatch.setattr(app_module, "button_dialog", lambda **kwargs: Dialog(next(actions)))

    def radio_dialog(**kwargs):
        selected_values.extend(kwargs["values"])
        return Dialog(None)

    monkeypatch.setattr(app_module, "radiolist_dialog", radio_dialog)

    app._users_menu()

    assert selected_values == [("alice", "alice — Linux account: present")]


def test_empty_share_templates_are_handled_without_radio_dialog(monkeypatch) -> None:
    app = bare_app()
    messages = []
    app._message = lambda title, text: messages.append((title, text))
    monkeypatch.setattr(app_module, "TEMPLATES", {})
    monkeypatch.setattr(
        app_module,
        "radiolist_dialog",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("radio list must not open")),
    )

    app._create_share()

    assert messages == [("New share", "No share templates are available.")]
