import pwd

from conftest import FakeRunner

from sambactl.samba.users import parse_pdbedit
from sambactl.system.users import LinuxUserManager


def test_parse_samba_users() -> None:
    users = parse_pdbedit("alice:1001:hash:data\nbob:1002:hash:data\nmalformed\n")
    assert [(user.username, user.uid) for user in users] == [("alice", 1001), ("bob", 1002)]


def test_linux_user_exists(monkeypatch) -> None:
    manager = LinuxUserManager(FakeRunner())
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda name: object() if name == "alice" else (_ for _ in ()).throw(KeyError()),
    )
    assert manager.exists("alice")
    assert not manager.exists("nobody-here")


def test_samba_password_not_in_arguments() -> None:
    from sambactl.samba.users import SambaUserManager

    runner = FakeRunner()
    SambaUserManager(runner).create("alice", "top-secret")
    assert "top-secret" not in " ".join(runner.calls[-1])
