from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sambactl import __version__
from sambactl.samba.service import SambaServiceManager
from sambactl.system.commands import CommandRunner


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Safe menu-driven Samba administration")
    result.add_argument("--config", type=Path, help="Use this smb.conf (primarily for testing)")
    result.add_argument(
        "--check", action="store_true", help="Run read-only checks against the Samba installation"
    )
    result.add_argument("--version", action="version", version=__version__)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    runner = CommandRunner()
    if args.check:
        try:
            from sambactl.smoke import read_only_check

            ready, output = read_only_check(runner, args.config)
            print(output)
            return 0 if ready else 1
        except (FileNotFoundError, PermissionError, OSError) as exc:
            print(f"sambactl: {exc}", file=sys.stderr)
            return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("sambactl requires an interactive terminal", file=sys.stderr)
        return 2
    try:
        from sambactl.tui.app import SambactlApp

        return SambactlApp(runner, SambaServiceManager(runner), args.config).run()
    except (FileNotFoundError, PermissionError) as exc:
        print(f"sambactl: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
