from __future__ import annotations

import grp
import os
import pwd
from pathlib import Path

from prompt_toolkit.shortcuts import (
    button_dialog,
    confirm,
    input_dialog,
    message_dialog,
    radiolist_dialog,
)
from prompt_toolkit.styles import Style

from sambactl import __version__
from sambactl.backup import BackupManager
from sambactl.models import OperationResult, ShareFilesystemPlan
from sambactl.paths import backup_directory
from sambactl.samba.config import SambaConfig
from sambactl.samba.shares import TEMPLATES, ShareManager, validate_share_name
from sambactl.samba.users import SambaUserManager
from sambactl.samba.validation import Validator
from sambactl.setup import inspect_system
from sambactl.system.filesystem import (
    directory_metadata,
    remove_empty_directory,
    safe_create_directory,
    set_directory_metadata,
)
from sambactl.system.identity import lookup_group, lookup_user, parse_mode, validate_username
from sambactl.system.users import LinuxUserManager, UserProvisioner
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


def _password_input(title: str, text: str) -> str | None:
    """Prompt for a password using the prompt_toolkit 3.0 public API."""
    return input_dialog(title=title, text=text, password=True, style=STYLE).run()


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
        self.provisioner = UserProvisioner(self.linux_users, self.samba_users)
        self.status = "Ready"

    def run(self) -> int:
        unavailable = [name for name, available in self.info.capabilities.items() if not available]
        if unavailable:
            self._message(
                "Dependency warning",
                "Unavailable features:\n"
                + "\n".join(f"- {name}" for name in unavailable)
                + "\n\nMissing commands: "
                + ", ".join(self.info.missing_commands),
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

    def _refresh_latest(self) -> None:
        """Refresh stale state before every submenu read or operation."""
        self._notice_external_change()

    def _select(
        self,
        *,
        title: str,
        text: str,
        values: list[tuple[str, str]],
        empty_message: str,
    ) -> str | None:
        """Open a radio list only when prompt_toolkit has something to select."""
        if not values:
            self._message(title, empty_message)
            return None
        return radiolist_dialog(
            title=title,
            text=text,
            values=values,
            style=STYLE,
        ).run()

    def _shares_menu(self) -> None:
        while True:
            self._refresh_latest()
            config = SambaConfig.read(self.info.config_path)
            choices = [(name, name) for name in config.share_names()] + [
                ("__create", "+ Create share"),
                ("__back", "Back"),
            ]
            selected = self._select(
                title="Shares",
                text="Select a share",
                values=[(value, label) for value, label in choices],
                empty_message="No share actions are available.",
            )
            if not selected or selected == "__back":
                return
            if selected == "__create":
                self._create_share()
            else:
                self._share_actions(selected)

    def _share_actions(self, name: str) -> None:
        self._refresh_latest()
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
        self._refresh_latest()
        template = self._select(
            title="New share",
            text="Choose a template",
            values=[(name, name) for name in TEMPLATES],
            empty_message="No share templates are available.",
        )
        if not template:
            return
        name = input_dialog(title="New share", text="Share name:", style=STYLE).run()
        try:
            validate_share_name(name or "")
        except ValueError as exc:
            self._message("Error", str(exc))
            return
        values = dict(TEMPLATES[template])
        defaults = {key: values.get(key, "") for key in COMMON_SHARE}
        defaults["path"] = f"/srv/samba/{name}"
        for key in COMMON_SHARE:
            value = input_dialog(
                title=f"New share [{name}]",
                text=f"{key}:",
                default=defaults[key],
                style=STYLE,
            ).run()
            if value is None:
                return
            if value:
                values[key] = value
            else:
                values.pop(key, None)
        path_text = values.get("path", "")
        if not path_text or not Path(path_text).is_absolute():
            self._message("Error", "An absolute directory path is required")
            return
        filesystem = self._directory_plan(template, Path(path_text))
        if filesystem is None:
            return
        if template == "Private Share" and not values.get("valid users"):
            values["valid users"] = filesystem.owner
        elif template == "Group Share":
            values["force group"] = filesystem.group
        elif template == "Public Read/Write":
            values["force user"] = filesystem.owner
            values["force group"] = filesystem.group
        proposed = SambaConfig.read(self.info.config_path)
        try:
            ShareManager.create(proposed, name, values)
            preflight = self.validator.preflight_share(
                self.info.config_path, proposed.render(), filesystem, values
            )
        except (OSError, ValueError) as exc:
            self._message("Preflight failed", str(exc))
            return
        summary = "\n".join(f"{key} = {value}" for key, value in values.items())
        summary += (
            f"\nowner = {filesystem.owner}\ngroup = {filesystem.group}"
            f"\nmode = {filesystem.mode:04o}\n\nPreflight: {preflight.status.value}"
        )
        if not preflight.ok:
            self._show_report("Share preflight", preflight, summary)
            return
        if template == "Public Read/Write" and not confirm(
            "Public writable shares allow unauthenticated writes. Continue?", default=False
        ):
            return
        if not confirm(f"Review proposed share:\n\n{summary}\n\nApply now?", default=True):
            return
        path = Path(path_text)
        created = False
        original_metadata = None
        try:
            owner = lookup_user(filesystem.owner)
            group = lookup_group(filesystem.group)
            if owner is None or group is None:
                raise ValueError("Selected owner or group no longer exists")
        except ValueError as exc:
            self._message("Error", str(exc))
            return
        if not path.exists():
            if not confirm(
                f"Create {path} as {filesystem.owner}:{filesystem.group} "
                f"mode {filesystem.mode:04o}?",
                default=True,
            ):
                return
            try:
                safe_create_directory(path, owner.id, group.id, filesystem.mode)
                created = True
            except (OSError, ValueError) as exc:
                self._message("Error", str(exc))
                return
        else:
            original_metadata = directory_metadata(path)
            if not confirm(
                f"Set {path} to {filesystem.owner}:{filesystem.group} mode {filesystem.mode:04o}?",
                default=True,
            ):
                return
            try:
                set_directory_metadata(path, owner.id, group.id, filesystem.mode)
            except OSError as exc:
                self._message("Error", str(exc))
                return
        result = self.transaction.apply(
            f"Create share [{name}]", lambda c: ShareManager.create(c, name, values)
        )
        if not result.ok and created:
            try:
                remove_empty_directory(path)
            except OSError:
                pass
        elif not result.ok and original_metadata:
            try:
                set_directory_metadata(path, *original_metadata)
            except OSError as exc:
                result.message += (
                    f" CRITICAL: directory metadata rollback failed ({exc}); manual intervention "
                    "may be required."
                )
        self._result(result)

    def _directory_plan(self, template: str, path: Path) -> ShareFilesystemPlan | None:
        default_owner, default_group, default_mode = "root", "root", "0755"
        if template == "Private Share":
            default_owner = (
                input_dialog(
                    title="Private share owner", text="Owning Linux/Samba user:", style=STYLE
                ).run()
                or ""
            )
            try:
                validate_username(default_owner)
                entry = pwd.getpwnam(default_owner)
                default_group = grp.getgrgid(entry.pw_gid).gr_name
            except (ValueError, KeyError) as exc:
                self._message("Invalid owner", str(exc) or "User does not exist")
                return None
            default_mode = "0700"
        elif template == "Group Share":
            default_group = (
                input_dialog(
                    title="Share group", text="Linux group with write access:", style=STYLE
                ).run()
                or ""
            )
            try:
                group_exists = lookup_group(default_group) is not None
            except ValueError:
                group_exists = False
            if not group_exists:
                self._message("Invalid group", f"Linux group {default_group!r} does not exist")
                return None
            default_mode = "2770"
        elif template == "Public Read/Write":
            default_owner, default_group, default_mode = "nobody", "nogroup", "2770"
        owner = input_dialog(
            title="Directory ownership", text="Owner:", default=default_owner, style=STYLE
        ).run()
        group = input_dialog(
            title="Directory ownership", text="Group:", default=default_group, style=STYLE
        ).run()
        mode_text = input_dialog(
            title="Directory permissions", text="Octal mode:", default=default_mode, style=STYLE
        ).run()
        if owner is None or group is None or mode_text is None:
            return None
        try:
            validate_username(owner)
            validate_username(group)
            mode = parse_mode(mode_text)
        except ValueError as exc:
            self._message("Invalid ownership or mode", str(exc))
            return None
        return ShareFilesystemPlan(path, owner, group, mode)

    def _delete_share(self, name: str) -> None:
        self._refresh_latest()
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
        self._refresh_latest()
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
        self._refresh_latest()
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
            self._refresh_latest()
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
            if action == "create":
                username = input_dialog(title="Samba user", text="Username:", style=STYLE).run()
            else:
                values = [
                    (
                        user.username,
                        f"{user.username} — Linux account: "
                        f"{self._linux_account_label(user.username)}",
                    )
                    for user in users
                ]
                username = self._select(
                    title="Select Samba user",
                    text=f"Choose account to {action}",
                    values=values,
                    empty_message="No Samba users are available.",
                )
            if not username:
                continue
            try:
                validate_username(username)
            except ValueError as exc:
                self._message("Invalid username", str(exc))
                continue
            if os.geteuid() != 0:
                self._message("Permission denied", "User changes require root privileges")
                continue
            if action == "create":
                self._create_user(username)
            elif action == "password":
                password = _password_input(title="Password", text="New password:")
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
        try:
            validate_username(username)
        except ValueError as exc:
            self._message("Invalid username", str(exc))
            return
        create_linux = False
        if not self.linux_users.exists(username):
            create_linux = confirm(
                "Linux account is missing. Create a non-interactive system account?", default=True
            )
            if not create_linux:
                self._message("Cancelled", "Samba requires a corresponding Linux account")
                return
        password = _password_input(
            title="Samba password", text="Password (never logged or stored):"
        )
        if not password:
            self.status = "User creation cancelled; no accounts were changed"
            return
        self._result(self.provisioner.create(username, password, create_linux=create_linux))

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
        self._refresh_latest()
        report = self.validator.dry_run(self.info.config_path)
        self._show_report("Validate / Dry Run", report, "No changes will be written.")

    def _backups_menu(self) -> None:
        self._refresh_latest()
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
            selected = self._select(
                title="Restore",
                text="Select a backup",
                values=[(str(p), p.name) for p in backups],
                empty_message="No backups are available yet.",
            )
            if selected and confirm(f"Restore {Path(selected).name}?", default=False):
                self._result(self.transaction.restore(Path(selected)))

    def _help_menu(self) -> None:
        text = (
            f"Sambactl {__version__} safely administers shares, users, selected global "
            "settings, validation and backups.\n\n"
            f"Configuration: {self.info.config_path}\n"
            f"Samba: {self.info.samba_version}\n"
            f"Mode: {self.info.service_mode}\n"
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

    def _show_report(self, title: str, report, prefix: str = "") -> None:
        lines = [f"Overall: {report.status.value}", prefix, ""]
        lines.extend(
            f"{check.status.value.upper()}: {check.name} — {check.detail}"
            for check in report.checks
        )
        self._message(title, "\n".join(lines))

    def _linux_account_label(self, username: str) -> str:
        try:
            return "yes" if self.linux_users.exists(username) else "no"
        except ValueError:
            return "invalid account name"

    @staticmethod
    def _message(title: str, text: str) -> None:
        message_dialog(title=title, text=text, style=STYLE).run()
