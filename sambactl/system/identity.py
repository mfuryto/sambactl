from __future__ import annotations

import grp
import pwd
import re
from dataclasses import dataclass

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}\$?$")


def validate_username(username: str) -> str:
    """Return a safe POSIX/Samba account name or raise ValueError."""
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Username must start with a lowercase letter or underscore, contain only "
            "lowercase letters, digits, underscores or hyphens, and be at most 32 characters"
        )
    return username


@dataclass(frozen=True)
class Identity:
    name: str
    id: int


def lookup_user(name: str) -> Identity | None:
    validate_username(name)
    try:
        entry = pwd.getpwnam(name)
        return Identity(entry.pw_name, entry.pw_uid)
    except KeyError:
        return None


def lookup_group(name: str) -> Identity | None:
    validate_username(name)
    try:
        entry = grp.getgrnam(name)
        return Identity(entry.gr_name, entry.gr_gid)
    except KeyError:
        return None


def parse_mode(value: str) -> int:
    if not re.fullmatch(r"[0-7]{3,4}", value):
        raise ValueError("Mode must be three or four octal digits")
    mode = int(value, 8)
    if mode & 0o002:
        raise ValueError("World-writable modes require an explicit external policy")
    return mode
