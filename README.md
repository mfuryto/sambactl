# Sambactl

[![CI](https://github.com/mfuryto/sambactl/actions/workflows/ci.yml/badge.svg)](https://github.com/mfuryto/sambactl/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/mfuryto/sambactl)](https://github.com/mfuryto/sambactl/releases/latest)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Safe, menu-driven Samba administration for Debian and Ubuntu servers.**

Sambactl provides a full-screen terminal interface for managing Samba shares,
local users, global settings, validation, and backups. It is designed for SSH
sessions and headless servers, with both keyboard and mouse navigation.

Instead of replacing `smb.conf`, Sambactl edits the existing configuration,
preserves unrelated content, validates every proposed change with `testparm`,
writes atomically, reloads the detected Samba service, and rolls back when an
operation fails.

> [!IMPORTANT]
> Sambactl changes system configuration and user accounts. Test it in a staging
> environment first and maintain an independent backup of production systems.

## Highlights

- Adaptive full-screen TUI built with `prompt_toolkit`
- Works over SSH without a desktop environment
- Mouse, arrow-key, Tab, and Enter navigation
- Guided share templates with safe permission defaults
- Separate workflows for creating and managing Samba users
- Common and advanced `[global]` configuration editing
- Automatic validation, backup, reload, and rollback
- Preserves comments, ordering, unknown directives, ownership, mode, ACL xattrs,
  and symlink targets where applicable
- Detects external changes before writing
- Read-only server readiness check with `sambactl --check`
- Tested compatibility with Ubuntu 22.04 LTS and modern Debian/Ubuntu releases

## Quick start

Download the latest Debian package from
[GitHub Releases](https://github.com/mfuryto/sambactl/releases/latest):

```bash
wget https://github.com/mfuryto/sambactl/releases/download/v0.1.1/sambactl_0.1.1-1_all.deb
sudo apt install ./sambactl_0.1.1-1_all.deb
```

Run a read-only readiness check:

```bash
sudo sambactl --check
```

Start the interactive interface:

```bash
sudo sambactl
```

APT installs the required runtime dependencies, including
`python3-prompt-toolkit`, `samba-common-bin`, and `systemd`.

## Interface

```text
┌────────────────────── Sambactl 0.1.1 ──────────────────────┐
│ Samba administration                                      │
│ Config: /etc/samba/smb.conf                               │
│ Status: Ready                                              │
│                                                            │
│ Shares            Create and manage shared folders         │
│ New user          Create a Samba login                     │
│ Edit users        Passwords, access, details and deletion  │
│ Global settings   Server-wide Samba options                │
│ Validate          Check configuration before applying      │
│ Backups           Create or restore snapshots              │
│ Help              Usage and version information            │
│                                                            │
│                         [ Exit ]                            │
└────────────────────────────────────────────────────────────┘
```

Use the mouse, `Tab`/`Shift+Tab`, or arrow keys to navigate. Press `Enter` to
activate a focused button. Within lists, `↑` and `↓` change the selected item;
within text fields, `←` and `→` move the cursor.

## What Sambactl manages

### Shares

- Discover, inspect, create, edit, and remove shares
- Start from private, group, public read-only, or public read/write templates
- Configure paths, users, groups, ownership, and optional advanced masks
- Validate the complete proposed configuration before writing
- Keep filesystem deletion separate and limited to empty directories

### Users

- Create matching Linux and Samba accounts
- Optionally create a home directory for new Linux accounts
- Change Samba passwords
- Allow or block Samba login without deleting files or Linux accounts
- View account status and delete Samba accounts

Passwords are passed to `smbpasswd -s` over standard input. They are never
placed in command arguments, persisted by Sambactl, or written to logs.

### Configuration and recovery

- Edit commonly used or arbitrary `[global]` options
- Validate syntax, paths, permissions, identities, services, and reload ability
- Create timestamped automatic or named preserved backups
- Restore backups through the same validated transaction path

## Safety model

Each configuration transaction:

1. Detects whether `smb.conf` changed externally.
2. Reads the latest configuration and validates the complete proposed file.
3. Creates a backup and preserves filesystem metadata.
4. Atomically replaces the resolved configuration target.
5. Validates the installed file and reloads the detected Samba service.
6. Restores, revalidates, and reloads the previous configuration on failure.

Automatic backups are stored beside the active configuration, normally in
`/etc/samba/backups/`. The newest ten automatic backups are retained. Named
manual backups are preserved until explicitly removed outside Sambactl.

## Requirements

- Debian or Ubuntu
- Python 3.10 or newer
- Samba tools: `testparm`, `smbpasswd`, and `pdbedit`
- systemd
- An interactive terminal
- Root privileges for configuration or account changes

Read-only inspection can run without root when the relevant files and commands
are accessible. The TUI manages classic file-backed `smb.conf` configurations
and the local Samba passdb workflow.

## Build from source

Build a Debian package:

```bash
sudo apt install build-essential debhelper dh-python pybuild-plugin-pyproject python3-all python3-setuptools
dpkg-buildpackage -us -uc -b
sudo apt install ../sambactl_0.1.1-1_all.deb
```

Development setup:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=sambactl
python -m build
```

For safe development against a disposable configuration:

```bash
SAMBACTL_CONFIG=/path/to/test/smb.conf sambactl
```

Never point development runs at production configuration. Automated tests use
temporary fixtures and mock system-changing commands.

## Known limitations

- Advanced editing intentionally exposes one `smb.conf` option at a time rather
  than attempting to model every Samba directive.
- `include = ...` directives are preserved, but shares defined in included files
  are not expanded into the main share list.
- Service verification confirms a successful `systemctl reload`; client-level
  connectivity tests remain an administrator responsibility.
- Active Directory domain-controller deployments require additional operational
  testing before production use.

## Contributing

Bug reports and focused pull requests are welcome. Please read
[CONTRIBUTING.md](CONTRIBUTING.md), open an issue for material changes, and use
the pull request template. Before submitting a change, run:

```bash
ruff check .
pytest --cov=sambactl
```

Please include the operating-system version, Samba version, and relevant error
output in bug reports. Never include passwords, password hashes, or private
configuration data.

Report suspected vulnerabilities privately according to
[SECURITY.md](SECURITY.md), not through public issues.

## License

Sambactl is available under the [MIT License](LICENSE).
