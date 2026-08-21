from __future__ import annotations

import importlib
import sys

import prompt_toolkit.shortcuts


def test_tui_import_does_not_require_password_dialog(monkeypatch) -> None:
    """Match Debian/Ubuntu builds where shortcuts.password_dialog is absent."""
    monkeypatch.delattr(prompt_toolkit.shortcuts, "password_dialog", raising=False)
    sys.modules.pop("sambactl.tui.app", None)

    module = importlib.import_module("sambactl.tui.app")

    assert module.SambactlApp


def test_action_dialog_uses_vertical_radio_list(monkeypatch) -> None:
    from sambactl.tui import app

    captured = {}

    def fake_choice(title, text, values, *, cancel_text):
        captured.update(title=title, text=text, values=values, cancel_text=cancel_text)
        return "users"

    monkeypatch.setattr(app, "_choice_dialog", fake_choice)

    selected = app._action_dialog(
        "Menu",
        "Choose an action",
        [("Shares", "shares"), ("Users", "users")],
        cancel_text="Exit",
    )

    assert selected == "users"
    assert captured["values"] == [("shares", "Shares"), ("users", "Users")]
    assert captured["cancel_text"] == "Exit"


def test_confirmation_uses_supported_dialog_api(monkeypatch) -> None:
    from sambactl.tui import app

    captured = {}

    def fake_choice(title, text, values, *, cancel_text):
        captured.update(title=title, text=text, values=values, cancel_text=cancel_text)
        return True

    monkeypatch.setattr(app, "_choice_dialog", fake_choice)

    assert app._confirm("Continue?", default=True)
    assert captured["values"] == [(True, "Yes"), (False, "No")]


def test_empty_backup_list_has_safe_placeholder() -> None:
    from sambactl.tui import app

    assert app._backup_choices([]) == [("", "No backups available")]


def test_tui_keeps_alternate_screen_for_whole_session(monkeypatch) -> None:
    from sambactl.tui import app

    events = []

    class Output:
        def enter_alternate_screen(self):
            events.append("enter")

        def quit_alternate_screen(self):
            events.append("quit")

        def flush(self):
            events.append("flush")

    instance = object.__new__(app.SambactlApp)
    monkeypatch.setattr(app, "create_output", lambda: Output())
    monkeypatch.setattr(instance, "_run_session", lambda: 7)

    assert instance.run() == 7
    assert events == ["enter", "flush", "quit", "flush"]
