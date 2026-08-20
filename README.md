# Sambactl

Sambactl is a menu-driven terminal application for practical Samba administration on modern Debian and Ubuntu systems. It edits the host's existing `smb.conf` surgically, validates changes with `testparm`, writes atomically, reloads detected Samba services, and rolls back automatically when installation or reload fails.

> **Maturity:** 0.1.0 is the first release candidate. Test it in a staging environment and keep an independent system backup before production use.

## Features

- `prompt_toolkit` TUI designed for headless machines and SSH: dark background, blue selection, clear result dialogs, and a persistent last-action status.
- Automatic active configuration discovery through `smbd -b`, with conventional-path fallback and `SAMBACTL_CONFIG` override.
- Existing share discovery, view/create/edit/delete, common templates, and arbitrary advanced option editing.
- Line-oriented configuration editing that retains comments, ordering, custom sections, unknown directives, and formatting wherever the edited line does not require change.
- Common and advanced `[global]` setting editing without replacing unrelated options.
- Samba user listing, creation, password change, enable/disable, status, and deletion through `pdbedit`/`smbpasswd`.
- Recommended creation of non-interactive Linux accounts where needed; Linux account deletion is always a separate confirmation and never removes home/data.
- Automatic timestamped backups beside the detected config, default retention of 10 automatic backups, and never-rotated preserved backups.
- Dry-run readiness report covering syntax, paths, safe write access, service detection, and reload prerequisites.
- Operation-specific share preflight covering the proposed config, owner/group/mode, paths, referenced accounts, backup access, and reload capability.
- External-change detection, process locking, preflight/post-write validation, metadata-preserving atomic replacement, automatic reload, and rollback.
- Startup dependency and Samba/service detection. Missing tools degrade affected features with a warning.

`prompt_toolkit` was chosen because it is mature, packaged by Debian/Ubuntu, lightweight, SSH-friendly, and provides accessible dialogs without requiring a desktop.

## Interface

```text
┌────────────── Sambactl 0.1.0 ──────────────┐
│ Samba administration                       │
│ Config: /etc/samba/smb.conf                │
│                                            │
│ [Shares] [Users] [Global Settings]         │
│ [Validate / Dry Run] [Backups / Restore]   │
│ [Help / About] [Exit]                      │
│                                            │
│ Status: Ready                              │
└────────────────────────────────────────────┘
```

## Requirements and platforms

Supported targets are maintained Debian and Ubuntu releases with Python 3.10+, Samba (`testparm`, `smbpasswd`, `pdbedit`), systemd, and `python3-prompt-toolkit`. Read-only inspection can run without root where permissions permit; system changes require root.

Sambactl manages the classic file-backed `smb.conf` and local Samba passdb workflow. Active Directory domain-controller deployments require extra operational testing; include-generated configuration is not rewritten in this release.

## Install and run

Build and install a Debian package:

```bash
sudo apt install build-essential debhelper dh-python pybuild-plugin-pyproject python3-all python3-setuptools
dpkg-buildpackage -us -uc -b
sudo apt install ../sambactl_0.1.0-1_all.deb
sudo sambactl
```

Read-only host inspection is available without starting the TUI and never creates state or backups:

```bash
sudo sambactl --check
```

The first run detects Samba, services, dependencies and the active config; creates the backup directory when privileged; records minimal setup state in `/var/lib/sambactl/state.json`; and enters the main menu. A separate wizard is not required.

For development:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=sambactl
python -m build
SAMBACTL_CONFIG=/path/to/test/smb.conf sambactl
```

Never point development runs at production configuration. Tests only use temporary fixtures and mock every system-changing command.

## Safety model

Every configuration edit re-checks the live file fingerprint, reads it again, validates the proposed complete file, creates a backup, atomically replaces the resolved config target while retaining its symlink, mode, ownership, extended attributes and POSIX ACL xattrs, validates the installed file, and reloads the active Samba service. Rollback is reported as successful only after the original file is restored, revalidated, reloaded, and fingerprinted. No normal manual reload action exists.

Automatic backups for `/etc/samba/smb.conf` live in `/etc/samba/backups/` as `smb.conf.YYYY-MM-DD_HH-MM-SS.bak`. The newest ten are retained. Names beginning `manual-` are preserved indefinitely. Restores use the same transaction and rollback path.

When creating a share directory, Sambactl proposes mode `2770`; it never chooses world-writable permissions. Share removal first deletes only configuration. Filesystem removal is separately confirmed and limited to empty directories.

Passwords are collected with hidden input and sent only to `smbpasswd -s` over stdin. They are never passed in command arguments, persisted, or logged.

## Known limitations

- The TUI edits one advanced key at a time; it intentionally does not attempt to model every Samba option.
- Direct `include = ...` files are preserved but their shares are not expanded into the main share list.
- Service verification is based on successful `systemctl reload`; deeper client connectivity checks remain manual.
- Linux account creation uses safe Samba-only system-account defaults and does not yet offer a full interactive-account customization screen.
- Full behavior still needs manual verification across standalone, member-server, and AD DC installations and across supported distribution releases.

## License

MIT. See [LICENSE](LICENSE).
