import grp
import pwd

import pytest

from sambactl.system.identity import lookup_group, lookup_user, parse_mode, validate_username


@pytest.mark.parametrize("name", ["alice", "build-user", "service_account", "machine$"])
def test_valid_usernames(name: str) -> None:
    assert validate_username(name) == name


@pytest.mark.parametrize(
    "name", ["", "-root", "--help", "Upper", "has space", "a/b", "name;id", "x" * 33]
)
def test_rejects_unsafe_usernames(name: str) -> None:
    with pytest.raises(ValueError):
        validate_username(name)


def test_modes_reject_world_writable_and_non_octal() -> None:
    assert parse_mode("2770") == 0o2770
    with pytest.raises(ValueError):
        parse_mode("0777")
    with pytest.raises(ValueError):
        parse_mode("banana")


def test_identity_lookups_return_ids_or_none(monkeypatch) -> None:
    user = type("Passwd", (), {"pw_name": "alice", "pw_uid": 1001})()
    group = type("Group", (), {"gr_name": "editors", "gr_gid": 1002})()
    monkeypatch.setattr(pwd, "getpwnam", lambda name: user)
    monkeypatch.setattr(grp, "getgrnam", lambda name: group)
    assert lookup_user("alice").id == 1001
    assert lookup_group("editors").id == 1002

    monkeypatch.setattr(pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    monkeypatch.setattr(grp, "getgrnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    assert lookup_user("missing") is None
    assert lookup_group("missing") is None
