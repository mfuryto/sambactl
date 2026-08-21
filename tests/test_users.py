import pwd

from conftest import FakeRunner

from sambactl.samba.users import parse_pdbedit
from sambactl.system.users import LinuxUserManager


def test_parse_samba_users() -> None:
    users = parse_pdbedit("alice:1001:hash:data\nbob:1002:hash:data\nmalformed\n")
    assert [(user.username, user.uid) for user in users] == [("alice", 1001), ("bob", 1002)]


def test_parse_verbose_samba_user_status() -> None:
    users = parse_pdbedit(
        "Unix username: alice\nUnix user ID: 1001\nAccount Flags: [U ]\n\n"
        "Unix username: bob\nUnix user ID: 1002\nAccount Flags: [DU ]\n"
    )

    assert [(user.username, user.uid, user.disabled) for user in users] == [
        ("alice", 1001, False),
        ("bob", 1002, True),
    ]


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


def test_linux_user_commands_use_option_separator(monkeypatch) -> None:
    runner = FakeRunner()
    manager = LinuxUserManager(runner)
    manager.create("alice")
    manager.delete("alice")
    assert runner.calls[0][-2:] == ("--", "alice")
    assert runner.calls[1][-2:] == ("--", "alice")


def test_linux_user_can_create_home_directory() -> None:
    runner = FakeRunner()

    LinuxUserManager(runner).create("alice", create_home=True)

    assert "--create-home" in runner.calls[0]
    assert "--no-create-home" not in runner.calls[0]
