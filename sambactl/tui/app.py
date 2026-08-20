from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit.shortcuts import (
    button_dialog,
    confirm,
    input_dialog,
    message_dialog,
    password_dialog,
    radiolist_dialog,
)
from prompt_toolkit.styles import Style

from sambactl import __version__
from sambactl.backup import BackupManager
from sambactl.models import OperationResult
from sambactl.paths import backup_directory
from sambactl.samba.config import SambaConfig
from sambactl.samba.shares import TEMPLATES, ShareManager
from sambactl.samba.users import SambaUserManager
from sambactl.samba.validation import Validator
from sambactl.setup import inspect_system
from sambactl.system.filesystem import remove_empty_directory, safe_create_directory
from sambactl.system.users import LinuxUserManager
from sambactl.transaction import ConfigTransaction

STYLE = Style.from_dict(
    {
        "dialog": "bg:#20242b #ffffff",
        "dialog frame.label": "#ffffff bold",
        "button": "#ffffff bg:#2952a3",
        "button.focused": "#ffffff bg:#177ddc bold",
        "dialog.body": "#ffffff bg:#20242b",
        "dialog shadow": "bg:#111111",
        "error": "#ff5555",
    }
)

COMMON_SHARE = (
    "path",
    "comment",
    "browseable",
    "read only",
    "guest ok",
    "valid users",
    "write list",
    "create mask",
    "directory mask",
)
COMMON_GLOBAL = (
    "workgroup",
    "server string",
    "security",
    "map to guest",
    "log level",
    "logging",
    "interfaces",
    "bind interfaces only",
)


class SambactlApp:
    def __init__(self, runner, services, config_path: Path | None = None) -> None:
        self.runner = runner
        self.services = services
        self.info = inspect_system(runner, config_path)
        self.backups = BackupManager(self.info.config_path, backup_directory(self.info.config_path))
        self.validator = Validator(runner, services)
        lock = Path(os.environ.get("SAMBACTL_LOCK", "/run/sambactl.lock"))
        self.transaction = ConfigTransaction(
            self.info.config_path, self.backups, self.validator, services, lock_path=lock
        )
        self.samba_users = SambaUserManager(runner)
        self.linux_users = LinuxUserManager(runner)
        self.status = "Ready"

    def run(self) -> int:
        if self.info.missing_commands:
            self._message(
                "Dependency warning",
                "Missing: "
                + ", ".join(self.info.missing_commands)
                + "\nAffected features may be unavailable.",
            )
        while True:
            self._notice_external_change()
            choice = button_dialog(
                title=f"Sambactl {__version__}",
                text=(
                    f"Samba administration\nConfig: {self.info.config_path}"
                    f"\n\nStatus: {self.status}"
                ),
                buttons=[
                    ("Shares", "shares"),
                    ("Users", "users"),
                    ("Global Settings", "global"),
                    ("Validate / Dry Run", "validate"),
                    ("Backups / Restore", "backups"),
                    ("Help / About", "help"),
                    ("Exit", "exit"),
                ],
                style=STYLE,
            ).run()
            if choice in (None, "exit"):
                return 0
            getattr(self, f"_{choice}_menu")()

    def _notice_external_change(self) -> None:
        if self.transaction.changed_externally():
            self.transaction.refresh()
            self.status = "Warning: smb.conf changed externally and was reloaded"
            self._message("External change", self.status)

    def _shares_menu(self) -> None:
        while True:
            config = SambaConfig.read(self.info.config_path)
            choices = [(name, name) for name in config.share_names()] + [
                ("__create", "+ Create share"),
                ("__back", "Back"),
            ]
            selected = radiolist_dialog(
                title="Shares",
                text="Select a share",
                values=[(value, label) for value, label in choices],
                style=STYLE,
            ).run()
            if not selected or selected == "__back":
                return
            if selected == "__create":
                self._create_share()
            else:
                self._share_actions(selected)

    def _share_actions(self, name: str) -> None:
        action = button_dialog(
            title=f"Share [{name}]",
            text=self._format_options(name),
            buttons=[
                ("View", "view"),
                ("Edit", "edit"),
                ("Advanced", "advanced"),
                ("Delete", "delete"),
                ("Back", "back"),
            ],
            style=STYLE,
        ).run()
        if action == "view":
            self._message(f"Share [{name}]", self._format_options(name))
        elif action in ("edit", "advanced"):
            self._edit_section(name, COMMON_SHARE if action == "edit" else None)
        elif action == "delete":
            self._delete_share(name)

    def _create_share(self) -> None:
        template = radiolist_dialog(
            title="New share",
            text="Choose a template",
            values=[(name, name) for name in TEMPLATES],
            style=STYLE,
        ).run()
        if not template:
            return
        name = input_dialog(title="New share", text="Share name:", style=STYLE).run()
        path_text = input_dialog(title="New share", text="Directory path:", style=STYLE).run()
        if not name or not path_text or not Path(path_text).is_absolute():
            self._message("Error", "A share name and absolute directory path are required")
            return
        path = Path(path_text)
        created = False
        if not path.exists():
            if not confirm(f"{path} does not exist. Create it with mode 2770?", default=True):
                return
            try:
                safe_create_directory(path)
                created = True
            except OSError as exc:
                self._message("Error", str(exc))
                return
        values = dict(TEMPLATES[template])
        values["path"] = str(path)
        result = self.transaction.apply(
            f"Create share [{name}]", lambda c: ShareManager.create(c, name, values)
        )
        if not result.ok and created:
            try:
                remove_empty_directory(path)
            except OSError:
                pass
        self._result(result)

    def _delete_share(self, name: str) -> None:
        path = SambaConfig.read(self.info.config_path).options(name).get("path")
        if not confirm(f"Remove share configuration [{name}]?", default=False):
            return
        result = self.transaction.apply(
            f"Delete share [{name}]", lambda c: ShareManager.delete(c, name)
        )
        self._result(result)
        if (
            result.ok
            and path
            and confirm(
                f"Also remove {path}? Only an empty directory can be removed.", default=False
            )
        ):
            try:
                remove_empty_directory(Path(path))
                self.status = f"Removed empty directory {path}"
            except OSError as exc:
                self._message(
                    "Directory retained", f"The share was removed, but no data was deleted: {exc}"
                )

    def _edit_section(self, name: str, fields: tuple[str, ...] | None) -> None:
        config = SambaConfig.read(self.info.config_path)
        current = config.options(name)
        if fields is None:
            key = input_dialog(title="Advanced setting", text="Option name:", style=STYLE).run()
            if not key:
                return
            fields = (key,)
        updates = {}
        for key in fields:
            value = input_dialog(
                title=f"[{name}]",
                text=f"{key} (blank removes it):",
                default=current.get(key, ""),
                style=STYLE,
            ).run()
            if value is None:
                return
            updates[key] = value or None
        result = self.transaction.apply(f"Update [{name}]", lambda c: c.set_options(name, updates))
        self._result(result)

    def _global_menu(self) -> None:
        action = button_dialog(
            title="Global Settings",
            text=self._format_options("global"),
            buttons=[("Common", "common"), ("Advanced", "advanced"), ("Back", None)],
            style=STYLE,
        ).run()
        if action:
            self._edit_section("global", COMMON_GLOBAL if action == "common" else None)

    def _users_menu(self) -> None:
        while True:
            users = self.samba_users.list() if self.runner.exists("pdbedit") else []
            action = button_dialog(
                title="Samba Users",
                text="\n".join(f"{u.username} (UID {u.uid or '?'})" for u in users)
                or "No users found",
                buttons=[
                    ("Create", "create"),
                    ("Password", "password"),
                    ("Enable", "enable"),
                    ("Disable", "disable"),
                    ("Status", "status"),
                    ("Delete", "delete"),
                    ("Back", None),
                ],
                style=STYLE,
            ).run()
            if not action:
                return
            username = input_dialog(title="Samba user", text="Username:", style=STYLE).run()
            if not username:
                continue
            if os.geteuid() != 0:
                self._message("Permission denied", "User changes require root privileges")
                continue
            if action == "create":
                self._create_user(username)
            elif action == "password":
                password = password_dialog(
                    title="Password", text="New password:", style=STYLE
                ).run()
                if password:
                    self._command_result(
                        self.samba_users.change_password(username, password), "Password changed"
                    )
            elif action == "status":
                result = self.samba_users.status(username)
                self._message("Account status", result.stdout or result.stderr)
            elif action == "delete":
                self._delete_user(username)
            else:
                self._command_result(getattr(self.samba_users, action)(username), f"User {action}d")

    def _create_user(self, username: str) -> None:
        if not self.linux_users.exists(username):
            if not confirm(
                "Linux account is missing. Create a non-interactive system account?", default=True
            ):
                self._message("Cancelled", "Samba requires a corresponding Linux account")
                return
            result = self.linux_users.create(username)
            if not result.ok:
                self._message("Error", result.stderr)
                return
        password = password_dialog(
            title="Samba password", text="Password (never logged or stored):", style=STYLE
        ).run()
        if password:
            self._command_result(self.samba_users.create(username, password), "Samba user created")

    def _delete_user(self, username: str) -> None:
        if not confirm(f"Delete Samba user {username}?", default=False):
            return
        result = self.samba_users.delete(username)
        self._command_result(result, "Samba user deleted")
        if (
            result.ok
            and self.linux_users.exists(username)
            and confirm("Also delete the Linux account (home/data is retained)?", default=False)
        ):
            self._command_result(self.linux_users.delete(username), "Linux account deleted")

    def _validate_menu(self) -> None:
        report = self.validator.dry_run(self.info.config_path)
        lines = [f"Overall: {report.status.value}", "", "No changes will be written."]
        lines.extend(
            f"{check.status.value}: {check.name} — {check.detail}" for check in report.checks
        )
        self._message("Validate / Dry Run", "\n".join(lines))

    def _backups_menu(self) -> None:
        action = button_dialog(
            title="Backups",
            text="Automatic backups retain the newest 10; manual backups are preserved.",
            buttons=[("List / Restore", "restore"), ("Create Preserved", "create"), ("Back", None)],
            style=STYLE,
        ).run()
        if action == "create":
            name = input_dialog(title="Preserved backup", text="Name:", style=STYLE).run()
            if name:
                try:
                    self.status = f"Created {self.backups.create_preserved(name).name}"
                except Exception as exc:
                    self._message("Error", str(exc))
        elif action == "restore":
            backups = self.backups.list()
            selected = radiolist_dialog(
                title="Restore",
                text="Select a backup",
                values=[(str(p), p.name) for p in backups],
                style=STYLE,
            ).run()
            if selected and confirm(f"Restore {Path(selected).name}?", default=False):
                self._result(self.transaction.restore(Path(selected)))

    def _help_menu(self) -> None:
        text = (
            f"Sambactl {__version__} safely administers shares, users, selected global "
            "settings, validation and backups.\n\n"
            f"Configuration: {self.info.config_path}\n"
            f"Samba: {self.info.samba_version}\n"
            f"Services: {', '.join(self.info.services) or 'none detected'}\n\n"
            "Configuration edits are validated, atomically installed, reloaded, and "
            "rolled back on failure. User passwords are passed directly to smbpasswd "
            "and never logged."
        )
        self._message(
            "Help / About",
            text,
        )

    def _format_options(self, section: str) -> str:
        values = SambaConfig.read(self.info.config_path).options(section)
        return "\n".join(f"{key} = {value}" for key, value in values.items()) or "No settings"

    def _command_result(self, result, success: str) -> None:
        self.status = (
            success if result.ok else f"Failed: {result.stderr.strip() or result.stdout.strip()}"
        )
        self._message("Success" if result.ok else "Error", self.status)

    def _result(self, result: OperationResult) -> None:
        self.status = result.message
        detail = result.message
        if result.report:
            detail += "\n" + "\n".join(
                f"{c.status.value}: {c.detail}" for c in result.report.checks
            )
        self._message("Success" if result.ok else "Error", detail)

    @staticmethod
    def _message(title: str, text: str) -> None:
        message_dialog(title=title, text=text, style=STYLE).run()
