from __future__ import annotations

import importlib
import inspect
import sys

import prompt_toolkit.shortcuts


def test_tui_import_does_not_require_password_dialog(monkeypatch) -> None:
    """Match Debian/Ubuntu builds where shortcuts.password_dialog is absent."""
    monkeypatch.delattr(prompt_toolkit.shortcuts, "password_dialog", raising=False)
    sys.modules.pop("sambactl.tui.app", None)

    module = importlib.import_module("sambactl.tui.app")

    assert module.input_dialog is prompt_toolkit.shortcuts.input_dialog


def test_supported_input_dialog_api_has_password_option() -> None:
    parameters = inspect.signature(prompt_toolkit.shortcuts.input_dialog).parameters

    assert "password" in parameters


def test_password_input_is_masked_and_not_emitted(monkeypatch, capsys) -> None:
    from sambactl.tui import app

    secret = "unique-dialog-secret"
    captured_options = {}

    class Dialog:
        def run(self):
            return secret

    def fake_input_dialog(**kwargs):
        captured_options.update(kwargs)
        return Dialog()

    monkeypatch.setattr(app, "input_dialog", fake_input_dialog)

    assert app._password_input("Password", "Enter password:") == secret
    assert captured_options["password"] is True
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
