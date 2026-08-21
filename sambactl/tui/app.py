from __future__ import annotations

import grp
import os
import pwd
from pathlib import Path

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import HSplit, Layout, VSplit
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.shortcuts import clear
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Box, Button, Checkbox, Frame, Label, RadioList, TextArea

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
        "sambactl": "bg:#20242b #ffffff",
        "frame": "#ffffff bg:#20242b",
        "frame.border": "#64748b bg:#20242b",
        "frame.label": "#ffffff bg:#20242b bold",
        "button": "#ffffff bg:#2952a3",
        "button.focused": "#ffffff bg:#177ddc bold",
        "text-area": "#f8fafc bg:#111827",
        "text-area.focused": "#ffffff bg:#1e3a5f",
        "input-field": "#f8fafc bg:#111827",
        "input-field focused": "#ffffff bg:#1e3a5f",
        "radio": "#dbeafe bg:#20242b",
        "radio-selected": "#7dd3fc bg:#20242b bold underline",
        "radio-checked": "#7dd3fc bg:#20242b bold",
        "radio-list": "bg:#20242b",
        "lead": "#cbd5e1 bg:#20242b",
        "hint": "#94a3b8 bg:#20242b italic",
        "section": "#7dd3fc bg:#20242b bold",
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
GLOBAL_LABELS = {
    "workgroup": "Windows workgroup",
    "server string": "Server description",
    "security": "Login method",
    "map to guest": "Unknown users",
    "log level": "Logging detail",
    "logging": "Log destination",
    "interfaces": "Network interfaces",
    "bind interfaces only": "Use only listed interfaces",
}

_SESSION_OUTPUT = None


class _PersistentScreenOutput:
    """Delegate rendering while keeping ownership of the alternate screen in SambactlApp."""

    def __init__(self, output) -> None:
        self._output = output

    def enter_alternate_screen(self) -> None:
        pass

    def quit_alternate_screen(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._output, name)


def _page(title: str, body, buttons: list[Button]):
    """Create a full-terminal adaptive page with persistent navigation keys."""
    bindings = KeyBindings()
    bindings.add("tab")(focus_next)
    bindings.add("s-tab")(focus_previous)

    def single_line_field_has_focus() -> bool:
        control = get_app().layout.current_control
        return isinstance(control, BufferControl) and not control.buffer.multiline()

    field_focused = Condition(single_line_field_has_focus)
    bindings.add("down", filter=field_focused, eager=True)(focus_next)
    bindings.add("up", filter=field_focused, eager=True)(focus_previous)
    for button in buttons:
        _enable_arrow_navigation(button)
    return Frame(
        HSplit(
            [
                Box(body, padding=1),
                Box(VSplit(buttons, padding=2), height=Dimension.exact(3)),
            ]
        ),
        title=title,
        # Do not use prompt_toolkit's ``dialog`` classes here. Its built-in
        # fallback theme paints dialog backgrounds bright purple, which can
        # leak into otherwise unstyled space below the frame title.
        style="class:sambactl",
        key_bindings=bindings,
    )


def _enable_arrow_navigation(button: Button) -> None:
    """Let arrow keys move focus when a button, rather than an editor, has focus."""
    button.control.key_bindings.add("right")(focus_next)
    button.control.key_bindings.add("down")(focus_next)
    button.control.key_bindings.add("left")(focus_previous)
    button.control.key_bindings.add("up")(focus_previous)


def _enable_list_navigation(widget: RadioList) -> RadioList:
    """Use horizontal arrows to leave a list while vertical arrows select items."""
    widget.control.key_bindings.add("right")(focus_next)
    widget.control.key_bindings.add("left")(focus_previous)
    return widget


def _checkbox(text: str) -> Checkbox:
    """Create a checkbox that can be reached and left with any arrow key."""
    widget = Checkbox(text=text)
    widget.control.key_bindings.add("right")(focus_next)
    widget.control.key_bindings.add("down")(focus_next)
    widget.control.key_bindings.add("left")(focus_previous)
    widget.control.key_bindings.add("up")(focus_previous)
    return widget


def _run_dialog(application):
    """Run a dialog inside Sambactl's persistent alternate screen."""
    application.full_screen = True
    # SIGWINCH already invalidates the application. Polling as well can cause
    # several seconds of competing redraws while a terminal is being resized.
    application.terminal_size_polling_interval = None
    application.min_redraw_interval = 0.05
    if _SESSION_OUTPUT is not None:
        application.output = _SESSION_OUTPUT
    clear()
    return application.run()


def _navigation_list(values, *, default):
    """Render actions as a clean navigation rail instead of a radio-button form."""
    return _enable_list_navigation(RadioList(
        values,
        default=default,
        open_character=" ",
        select_character="›",
        close_character="",
        container_style="class:sambactl",
        show_scrollbar=len(values) > 8,
    ))


def _choice_dialog(
    title: str,
    text: str,
    values,
    *,
    cancel_text: str = "Back",
    extra_buttons: list[tuple[str, str]] | None = None,
):
    choices = _navigation_list(values, default=values[0][0])

    def select(_event=None) -> None:
        get_app().exit(result=choices.current_value)

    # Menus are navigation, not forms: Enter opens the highlighted item
    # immediately. The button remains available for mouse-only navigation.
    choices.control.key_bindings.add("enter")(select)

    footer_buttons = [Button("Select", handler=select)]
    for label, value in extra_buttons or []:
        footer_buttons.append(
            Button(label, handler=lambda selected=value: get_app().exit(result=selected))
        )
    footer_buttons.append(Button(cancel_text, handler=lambda: get_app().exit()))

    page = _page(
        title,
        HSplit(
            [
                Box(Label(text, style="class:lead"), padding_bottom=1),
                Box(choices, height=Dimension(weight=1)),
                Label("↑/↓ navigate   Enter select   Tab move", style="class:hint"),
            ]
        ),
        footer_buttons,
    )
    return _run_dialog(Application(layout=Layout(page, focused_element=choices), style=STYLE))


def _action_dialog(
    title: str,
    text: str,
    actions: list[tuple[str, str]],
    *,
    cancel_text: str = "Back",
) -> str | None:
    """Show actions vertically so menus remain usable in narrow terminals."""
    return _choice_dialog(
        title,
        text,
        [(value, label) for label, value in actions],
        cancel_text=cancel_text,
    )


def _main_menu(title: str, text: str) -> str | None:
    """Present top-level destinations as directly clickable buttons."""
    destinations = [
        ("Shares", "Create and manage shared folders", "shares"),
        ("New user", "Create a Samba login", "new_users"),
        ("Edit users", "Passwords, access, details and deletion", "edit_users"),
        ("Global settings", "Server-wide Samba options", "global"),
        ("Validate", "Check configuration before applying", "validate"),
        ("Backups", "Create or restore snapshots", "backups"),
        ("Help", "Usage and version information", "help"),
    ]
    buttons = []
    rows = []
    for label, description, value in destinations:
        button = Button(
            label,
            handler=lambda selected=value: get_app().exit(result=selected),
            width=20,
            left_symbol="",
            right_symbol="",
        )
        _enable_arrow_navigation(button)
        buttons.append(button)
        rows.append(VSplit([button, Label(description, style="class:lead")], padding=2))

    page = _page(
        title,
        HSplit(
            [
                Box(Label(text, style="class:lead"), padding_bottom=1),
                HSplit(rows, padding=1),
                Label("Click a button, or use Tab and Enter.", style="class:hint"),
            ]
        ),
        [
            Button(
                "Exit",
                handler=lambda: get_app().exit(),
                left_symbol="",
                right_symbol="",
            )
        ],
    )
    return _run_dialog(Application(layout=Layout(page, focused_element=buttons[0]), style=STYLE))


def _share_action_dialog(name: str, details: str) -> str | None:
    """Show the selected share and keep its actions together as direct buttons."""
    actions = []
    for label, value in [
        ("Edit", "edit"),
        ("Advanced", "advanced"),
        ("Delete", "delete"),
        ("Back", None),
    ]:
        actions.append(
            Button(
                label,
                handler=lambda selected=value: get_app().exit(result=selected),
                left_symbol="",
                right_symbol="",
            )
        )
    page = _page(
        f"Share [{name}]",
        HSplit(
            [
                Label("Current configuration", style="class:lead"),
                Label(details),
                Label("Choose an action below.", style="class:hint"),
            ],
            padding=1,
        ),
        actions,
    )
    return _run_dialog(
        Application(layout=Layout(page, focused_element=actions[0]), style=STYLE)
    )


def _confirm(text: str, *, default: bool = False) -> bool:
    """Show a prompt_toolkit-version-independent confirmation dialog."""
    values = [(default, "Yes" if default else "No"), (not default, "No" if default else "Yes")]
    return bool(_choice_dialog("Confirm", text, values, cancel_text="Cancel"))


def _share_form(
    initial: dict[str, str | bool] | None = None, error: str = ""
) -> dict[str, str | bool] | None:
    """Collect a complete share definition in one compact, keyboard-friendly form."""
    initial = initial or {}
    selected_template = str(initial.get("template", next(iter(TEMPLATES))))
    template = _enable_list_navigation(
        RadioList(
            [(name, name) for name in TEMPLATES],
            default=selected_template,
            container_style="class:sambactl",
        )
    )
    boolean_keys = ("browseable", "read only", "guest ok")
    boolean_labels = {
        "browseable": "Visible in network browser",
        "read only": "Read only",
        "guest ok": "Allow guest access",
    }
    template_defaults = TEMPLATES[selected_template]
    editors = {
        "name": TextArea(text=str(initial.get("name", "")), multiline=False, height=1),
        **{
            key: TextArea(
                text=str(initial.get(key, template_defaults.get(key, ""))),
                multiline=False,
                height=1,
            )
            for key in COMMON_SHARE
            if key not in boolean_keys
        },
        "owner": TextArea(text=str(initial.get("owner", "")), multiline=False, height=1),
        "group": TextArea(text=str(initial.get("group", "")), multiline=False, height=1),
    }
    boolean_controls = {key: _checkbox(boolean_labels[key]) for key in boolean_keys}
    for key, control in boolean_controls.items():
        value = str(initial.get(key, template_defaults.get(key, "no"))).lower()
        control.checked = value == "yes"
    public_write = _checkbox("Allow unauthenticated writes for Public Read/Write")
    public_write.checked = bool(initial.get("allow_public_write", False))
    advanced = _checkbox("Show advanced file permission settings")
    advanced.checked = bool(initial.get("show_advanced", False))

    labels = {
        "name": "Share name",
        "path": "Path",
        "comment": "Description",
        "valid users": "Allowed users/groups",
        "write list": "Users/groups allowed write",
        "create mask": "New file mask",
        "directory mask": "New directory mask",
        "owner": "Directory owner",
        "group": "Directory group",
    }
    rows = [
        VSplit([Label(labels.get(key, key), width=18), editor], padding=1)
        for key, editor in editors.items()
    ]

    def save() -> None:
        result: dict[str, str | bool] = {
            "template": template.current_value,
            "allow_public_write": public_write.checked,
            "show_advanced": advanced.checked,
            "mode": "",
        }
        result.update({key: editor.text.strip() for key, editor in editors.items()})
        result.update(
            {key: "yes" if control.checked else "no" for key, control in boolean_controls.items()}
        )
        get_app().exit(result=result)

    def load_template() -> None:
        defaults = TEMPLATES[str(template.current_value)]
        for key, control in boolean_controls.items():
            control.checked = defaults.get(key, "no") == "yes"
        for key in ("create mask", "directory mask"):
            editors[key].text = defaults.get(key, "")
        get_app().invalidate()

    basic_rows = [rows[index] for index in (0, 1, 2)]
    access_rows = [rows[index] for index in (3, 4, 7, 8)]
    advanced_rows = [rows[index] for index in (5, 6)]
    advanced_panel = ConditionalContainer(
        HSplit(
            [
                *advanced_rows,
                Label(
                    "Normally you can leave these unchanged. The selected share type loads "
                    "safe defaults for new files and directories.",
                    style="class:hint",
                ),
            ]
        ),
        filter=Condition(lambda: advanced.checked),
    )
    body = [
        Label("1  Share type", style="class:section"),
        HSplit(
            [
                Box(template, height=5, style="class:sambactl"),
            ],
            style="class:sambactl",
        ),
        Label("2  Basic information", style="class:section"),
        *basic_rows,
        Label("3  Access", style="class:section"),
        VSplit(list(boolean_controls.values()), padding=2),
        *access_rows,
        public_write,
        advanced,
        advanced_panel,
    ]
    if error:
        body.insert(0, Label(f"Error: {error}", style="class:error"))
    page = _page(
        "Create share",
        HSplit(body),
        [
            Button("Load defaults", handler=load_template),
            Button("Save", handler=save),
            Button("Cancel", handler=lambda: get_app().exit()),
        ],
    )
    return _run_dialog(
        Application(
            layout=Layout(page, focused_element=editors["name"]),
            style=STYLE,
            mouse_support=True,
        )
    )


def _fields_form(
    title: str,
    fields: list[tuple[str, str, str]],
    *,
    help_text: str = "",
) -> dict[str, str] | None:
    """Edit related values together and return them from one Save action."""
    editors = {
        key: TextArea(text=default, multiline=False, height=1)
        for key, _label, default in fields
    }
    rows = [
        VSplit([Label(label, width=22), editors[key]], padding=1)
        for key, label, _default in fields
    ]

    def save() -> None:
        get_app().exit(result={key: editor.text.strip() for key, editor in editors.items()})

    body = ([Label(help_text)] if help_text else []) + rows
    page = _page(
        title,
        HSplit(body),
        [Button("Save", handler=save), Button("Cancel", handler=lambda: get_app().exit())],
    )
    return _run_dialog(
        Application(
            layout=Layout(page, focused_element=next(iter(editors.values()))),
            style=STYLE,
            mouse_support=True,
        )
    )


def _new_user_form() -> dict[str, str | bool] | None:
    """Collect only the information needed to create a Samba user."""
    username = TextArea(multiline=False, height=1)
    password = TextArea(multiline=False, password=True, height=1)
    create_linux = _checkbox("Create the required Linux account if it is missing")
    create_home = _checkbox("Create a home directory for the new Linux account")

    def create() -> None:
        get_app().exit(
            result={
                "username": username.text.strip(),
                "password": password.text,
                "create_linux": create_linux.checked,
                "create_home": create_home.checked,
            }
        )

    page = _page(
        "New Samba user",
        HSplit(
            [
                Label(
                    "A Samba login must have a matching Linux account. The password is passed "
                    "directly to Samba and is never stored by sambactl.",
                    style="class:lead",
                ),
                VSplit([Label("Username", width=18), username], padding=1),
                VSplit([Label("Samba password", width=18), password], padding=1),
                create_linux,
                create_home,
            ],
            padding=1,
        ),
        [Button("Create user", handler=create), Button("Back", handler=lambda: get_app().exit())],
    )
    return _run_dialog(
        Application(
            layout=Layout(page, focused_element=username),
            style=STYLE,
            mouse_support=True,
        )
    )


def _edit_user_form(accounts: list[tuple[str, str]]) -> dict[str, str | bool] | None:
    """Select one existing user and run a clearly labelled account action."""
    account = _enable_list_navigation(
        RadioList(
            accounts or [("", "No existing Samba users")],
            default="",
            container_style="class:sambactl",
        )
    )
    password = TextArea(multiline=False, password=True, height=1)
    delete_linux = _checkbox("Also delete Linux account (home/data retained)")

    def finish(action: str) -> None:
        get_app().exit(
            result={
                "action": action,
                "account": account.current_value,
                "password": password.text,
                "delete_linux": delete_linux.checked,
            }
        )

    action_specs = [
        ("Change password", "password"),
        ("Allow login", "enable"),
        ("Block login", "disable"),
        ("View details", "status"),
        ("Delete user", "delete"),
    ]
    action_buttons = [
        Button(
            label,
            handler=lambda selected=action: finish(selected),
            width=18,
            left_symbol="",
            right_symbol="",
        )
        for label, action in action_specs
    ]
    for button in action_buttons:
        _enable_arrow_navigation(button)

    page = _page(
        "Edit Samba users",
        HSplit(
            [
                Label("Choose an account", style="class:lead"),
                HSplit(
                    [
                        Box(
                            account,
                            height=Dimension(min=4, preferred=7, weight=1),
                            style="class:sambactl",
                        ),
                    ],
                    style="class:sambactl",
                ),
                Label(
                    "Allow/block controls Samba login only; it does not change files or the "
                    "Linux account.",
                    style="class:hint",
                ),
                VSplit([Label("New password", width=18), password], padding=1),
                Label("Choose an action", style="class:lead"),
                VSplit(action_buttons[:3], padding=2),
                VSplit(action_buttons[3:], padding=2),
                delete_linux,
            ]
        ),
        [Button("Back", handler=lambda: get_app().exit())],
    )
    return _run_dialog(
        Application(
            layout=Layout(page, focused_element=account),
            style=STYLE,
            mouse_support=True,
        )
    )


def _backup_choices(backups: list[Path]) -> list[tuple[str, str]]:
    """RadioList requires at least one item, including when no backups exist."""
    return [(str(path), path.name) for path in backups] or [("", "No backups available")]


def _backup_form(backups: list[Path]) -> dict[str, str] | None:
    """Collect backup creation or restore choices on one page."""
    action = _navigation_list(
        [("create", "Create preserved backup"), ("restore", "Restore backup")],
        default="create",
    )
    selected = _enable_list_navigation(RadioList(_backup_choices(backups), default=""))
    name = TextArea(multiline=False, height=1)

    def apply() -> None:
        get_app().exit(
            result={
                "action": action.current_value,
                "backup": selected.current_value,
                "name": name.text.strip(),
            }
        )

    page = _page(
        "Backups",
        HSplit(
            [
                HSplit(
                    [
                        Label("Action", style="class:sambactl"),
                        Box(action, height=2, style="class:sambactl"),
                    ],
                    style="class:sambactl",
                ),
                HSplit(
                    [
                        Label("Backup", style="class:sambactl"),
                        Box(selected, height=4, style="class:sambactl"),
                    ],
                    style="class:sambactl",
                ),
                VSplit([Label("Preserved name", width=18), name], padding=1),
            ]
        ),
        [Button("Apply", handler=apply), Button("Back", handler=lambda: get_app().exit())],
    )
    return _run_dialog(
        Application(
            layout=Layout(page, focused_element=action),
            style=STYLE,
            mouse_support=True,
        )
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
        self.provisioner = UserProvisioner(self.linux_users, self.samba_users)
        self.status = "Ready"

    def run(self) -> int:
        global _SESSION_OUTPUT
        output = create_output()
        output.enter_alternate_screen()
        output.flush()
        _SESSION_OUTPUT = _PersistentScreenOutput(output)
        try:
            return self._run_session()
        finally:
            _SESSION_OUTPUT = None
            output.quit_alternate_screen()
            output.flush()

    def _run_session(self) -> int:
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
            choice = _main_menu(
                f"Sambactl {__version__}",
                (
                    f"Samba administration\nConfig: {self.info.config_path}"
                    f"\n\nStatus: {self.status}"
                ),
            )
            if choice is None:
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

    def _shares_menu(self) -> None:
        while True:
            self._refresh_latest()
            config = SambaConfig.read(self.info.config_path)
            choices = [(name, name) for name in config.share_names()]
            selected = _choice_dialog(
                "Shares",
                "Select a share",
                [(value, label) for value, label in choices]
                or [("", "No shares configured")],
                extra_buttons=[("Create share", "__create")],
            )
            if not selected:
                return
            if selected == "__create":
                self._create_share()
            else:
                self._share_actions(selected)

    def _share_actions(self, name: str) -> None:
        self._refresh_latest()
        action = _share_action_dialog(name, self._format_options(name))
        if action in ("edit", "advanced"):
            self._edit_section(name, COMMON_SHARE if action == "edit" else None)
        elif action == "delete":
            self._delete_share(name)

    def _create_share(self) -> None:
        self._refresh_latest()
        if not TEMPLATES:
            self._message("New share", "No share templates are available.")
            return
        form = None
        error = ""
        while True:
            form = _share_form(form, error)
            if not form:
                return
            error = ""
            template = str(form["template"])
            name = str(form["name"])
            try:
                validate_share_name(name)
            except ValueError as exc:
                error = str(exc)
                continue
            values = dict(TEMPLATES[template])
            for key in COMMON_SHARE:
                value = str(form[key])
                if value:
                    values[key] = value
            values.setdefault("path", f"/srv/samba/{name}")
            path_text = values.get("path", "")
            if not path_text or not Path(path_text).is_absolute():
                error = "An absolute directory path is required"
                continue
            try:
                filesystem = self._directory_plan(
                    template,
                    Path(path_text),
                    str(form["owner"]),
                    str(form["group"]),
                    str(form["mode"]),
                )
            except ValueError as exc:
                error = str(exc)
                continue
            if template == "Private Share" and not values.get("valid users"):
                values["valid users"] = filesystem.owner
            elif template == "Group Share":
                values["force group"] = filesystem.group
            elif template == "Public Read/Write":
                values["force user"] = filesystem.owner
                values["force group"] = filesystem.group
            if template == "Public Read/Write" and not form["allow_public_write"]:
                error = "Allow unauthenticated writes before saving a public writable share"
                continue
            proposed = SambaConfig.read(self.info.config_path)
            try:
                ShareManager.create(proposed, name, values)
                preflight = self.validator.preflight_share(
                    self.info.config_path, proposed.render(), filesystem, values
                )
            except (OSError, ValueError) as exc:
                error = f"Preflight failed: {exc}"
                continue
            if not preflight.ok:
                error = "; ".join(
                    f"{check.name}: {check.detail}"
                    for check in preflight.checks
                    if check.status.value == "FAILED"
                ) or "Share preflight failed"
                continue
            break
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
            try:
                safe_create_directory(path, owner.id, group.id, filesystem.mode)
                created = True
            except (OSError, ValueError) as exc:
                self._message("Error", str(exc))
                return
        else:
            original_metadata = directory_metadata(path)
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

    def _directory_plan(
        self, template: str, path: Path, owner_text: str, group_text: str, mode_text: str
    ) -> ShareFilesystemPlan:
        default_owner, default_group, default_mode = "root", "root", "0755"
        if template == "Private Share":
            default_owner = owner_text
            try:
                validate_username(default_owner)
                entry = pwd.getpwnam(default_owner)
                default_group = grp.getgrgid(entry.pw_gid).gr_name
            except (ValueError, KeyError) as exc:
                raise ValueError(str(exc) or "User does not exist") from exc
            default_mode = "0700"
        elif template == "Group Share":
            default_group = group_text
            try:
                group_exists = lookup_group(default_group) is not None
            except ValueError:
                group_exists = False
            if not group_exists:
                raise ValueError(f"Linux group {default_group!r} does not exist")
            default_mode = "2770"
        elif template == "Public Read/Write":
            default_owner, default_group, default_mode = "nobody", "nogroup", "2770"
        owner = owner_text or default_owner
        group = group_text or default_group
        mode_text = mode_text or default_mode
        try:
            validate_username(owner)
            validate_username(group)
            mode = parse_mode(mode_text)
        except ValueError as exc:
            raise ValueError(f"Invalid ownership or mode: {exc}") from exc
        return ShareFilesystemPlan(path, owner, group, mode)

    def _delete_share(self, name: str) -> None:
        self._refresh_latest()
        path = SambaConfig.read(self.info.config_path).options(name).get("path")
        if not _confirm(f"Remove share configuration [{name}]?"):
            return
        result = self.transaction.apply(
            f"Delete share [{name}]", lambda c: ShareManager.delete(c, name)
        )
        self._result(result)
        if (
            result.ok
            and path
            and _confirm(f"Also remove {path}? Only an empty directory can be removed.")
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
            form = _fields_form(
                f"Advanced setting [{name}]",
                [("key", "Option name", ""), ("value", "Value (blank removes)", "")],
            )
            if not form or not form["key"]:
                return
            updates = {form["key"]: form["value"] or None}
        else:
            labels = GLOBAL_LABELS if name == "global" else {}
            help_text = (
                "These are the most commonly used server settings. Blank values remove the "
                "setting and let Samba use its default. Changes are validated before saving."
                if name == "global"
                else "Blank values remove the option."
            )
            form = _fields_form(
                f"Edit [{name}]",
                [(key, labels.get(key, key), current.get(key, "")) for key in fields],
                help_text=help_text,
            )
            if form is None:
                return
            updates = {key: value or None for key, value in form.items()}
        result = self.transaction.apply(f"Update [{name}]", lambda c: c.set_options(name, updates))
        self._result(result)

    def _global_menu(self) -> None:
        self._refresh_latest()
        action = _action_dialog(
            title="Global Settings",
            text=(
                "Settings that apply to the whole Samba server, not just one share.\n\n"
                "Current configuration:\n" + self._format_options("global")
            ),
            actions=[
                ("Common settings — guided names for everyday options", "common"),
                ("Advanced option — edit a raw smb.conf key", "advanced"),
            ],
        )
        if action:
            self._edit_section("global", COMMON_GLOBAL if action == "common" else None)

    def _new_users_menu(self) -> None:
        form = _new_user_form()
        if form:
            self._create_user(form)

    def _edit_users_menu(self) -> None:
        while True:
            self._refresh_latest()
            users = self.samba_users.list() if self.runner.exists("pdbedit") else []
            form = _edit_user_form(
                [
                    (
                        user.username,
                        f"{user.username} — Samba: "
                        f"{'Blocked' if user.disabled else 'Allowed'} — Linux: "
                        f"{self._linux_account_label(user.username)}",
                    )
                    for user in users
                ]
            )
            if not form:
                return
            action = str(form["action"])
            username = str(form["account"])
            if not username:
                self._message("No user selected", "Select an existing Samba user.")
                continue
            try:
                validate_username(username)
            except ValueError as exc:
                self._message("Invalid username", str(exc))
                continue
            if os.geteuid() != 0:
                self._message("Permission denied", "User changes require root privileges")
                continue
            if action == "password":
                password = str(form["password"])
                if password:
                    self._command_result(
                        self.samba_users.change_password(username, password), "Password changed"
                    )
                else:
                    self._message("Password required", "Enter the new password before applying.")
            elif action == "status":
                result = self.samba_users.status(username)
                self._message("Account status", result.stdout or result.stderr)
            elif action == "delete":
                self._delete_user(username, delete_linux=bool(form["delete_linux"]))
            else:
                self._command_result(getattr(self.samba_users, action)(username), f"User {action}d")

    def _create_user(self, form: dict[str, str | bool]) -> None:
        if os.geteuid() != 0:
            self._message("Permission denied", "Creating users requires root privileges")
            return
        username = str(form["username"])
        try:
            validate_username(username)
        except ValueError as exc:
            self._message("Invalid username", str(exc))
            return
        create_linux = bool(form["create_linux"])
        create_home = bool(form["create_home"])
        if not self.linux_users.exists(username) and not create_linux:
            self._message("Cancelled", "Samba requires a corresponding Linux account")
            return
        password = str(form["password"])
        if not password:
            self.status = "User creation cancelled; no accounts were changed"
            return
        self._result(
            self.provisioner.create(
                username,
                password,
                create_linux=create_linux,
                create_home=create_home,
            )
        )

    def _delete_user(self, username: str, *, delete_linux: bool = False) -> None:
        if not _confirm(f"Delete Samba user {username}?"):
            return
        result = self.samba_users.delete(username)
        self._command_result(result, "Samba user deleted")
        if result.ok and delete_linux and self.linux_users.exists(username):
            self._command_result(self.linux_users.delete(username), "Linux account deleted")

    def _validate_menu(self) -> None:
        self._refresh_latest()
        report = self.validator.dry_run(self.info.config_path)
        self._show_report("Validate / Dry Run", report, "No changes will be written.")

    def _backups_menu(self) -> None:
        self._refresh_latest()
        form = _backup_form(self.backups.list())
        if not form:
            return
        action = form["action"]
        if action == "create":
            name = form["name"]
            if name:
                try:
                    self.status = f"Created {self.backups.create_preserved(name).name}"
                except Exception as exc:
                    self._message("Error", str(exc))
            else:
                self._message("Name required", "Enter a name for the preserved backup.")
        elif action == "restore":
            selected = form["backup"]
            if not selected:
                self._message("No backup selected", "There are no backups available to restore.")
            elif _confirm(f"Restore {Path(selected).name}?"):
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
        page = _page(
            title,
            Label(text),
            [Button("OK", handler=lambda: get_app().exit())],
        )
        _run_dialog(Application(layout=Layout(page), style=STYLE))
