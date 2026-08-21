from sambactl.system.commands import CommandResult
from sambactl.system.users import UserProvisioner


class FakeLinux:
    def __init__(self, existed=False, create_ok=True, delete_ok=True):
        self.existed = existed
        self.create_ok = create_ok
        self.delete_ok = delete_ok
        self.created = []
        self.deleted = []

    def exists(self, username):
        return self.existed

    def create(self, username, *, create_home=False):
        self.created.append((username, create_home))
        return CommandResult(
            ("useradd", username), 0 if self.create_ok else 1, stderr="useradd denied"
        )

    def delete(self, username):
        self.deleted.append(username)
        return CommandResult(("userdel", username), 0 if self.delete_ok else 1, stderr="denied")


class FakeSamba:
    def __init__(self, ok, detail="failed", raises=False):
        self.ok = ok
        self.detail = detail
        self.raises = raises
        self.called = False

    def create(self, username, password):
        self.called = True
        if self.raises:
            raise RuntimeError(self.detail)
        return CommandResult(("smbpasswd", username), 0 if self.ok else 1, stderr=self.detail)


def test_new_linux_user_is_removed_if_samba_creation_fails() -> None:
    linux = FakeLinux()
    result = UserProvisioner(linux, FakeSamba(False)).create("alice", "secret", create_linux=True)
    assert not result.ok
    assert linux.created == [("alice", False)]
    assert linux.deleted == ["alice"]
    assert "rolled back" in result.message


def test_preexisting_linux_user_is_never_removed() -> None:
    linux = FakeLinux(existed=True)
    result = UserProvisioner(linux, FakeSamba(False)).create("alice", "secret", create_linux=True)
    assert not result.ok
    assert linux.deleted == []


def test_linux_rollback_failure_is_critical() -> None:
    linux = FakeLinux(delete_ok=False)
    result = UserProvisioner(linux, FakeSamba(False)).create("alice", "secret", create_linux=True)
    assert "CRITICAL" in result.message


def test_success_keeps_new_linux_account() -> None:
    linux = FakeLinux()
    result = UserProvisioner(linux, FakeSamba(True)).create("alice", "secret", create_linux=True)
    assert result.ok
    assert linux.deleted == []


def test_declining_linux_creation_changes_nothing() -> None:
    linux = FakeLinux()
    samba = FakeSamba(True)
    result = UserProvisioner(linux, samba).create("alice", "secret", create_linux=False)
    assert not result.ok
    assert linux.created == []
    assert not samba.called


def test_useradd_failure_does_not_attempt_samba_or_rollback() -> None:
    linux = FakeLinux(create_ok=False)
    samba = FakeSamba(True)
    result = UserProvisioner(linux, samba).create("alice", "secret", create_linux=True)
    assert not result.ok
    assert "useradd denied" in result.message
    assert not samba.called
    assert linux.deleted == []


def test_invalid_username_runs_no_commands() -> None:
    linux = FakeLinux()
    samba = FakeSamba(True)
    try:
        UserProvisioner(linux, samba).create("--help", "secret", create_linux=True)
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe username was accepted")
    assert linux.created == []
    assert not samba.called


def test_password_is_redacted_from_tool_output_and_exceptions(capsys) -> None:
    password = "unique-super-secret"
    for samba in (
        FakeSamba(False, f"tool echoed {password}"),
        FakeSamba(False, f"exception echoed {password}", raises=True),
    ):
        linux = FakeLinux(existed=True)
        result = UserProvisioner(linux, samba).create("alice", password, create_linux=True)
        assert password not in result.message
        assert "[REDACTED]" in result.message
    captured = capsys.readouterr()
    assert password not in captured.out
    assert password not in captured.err


def test_home_directory_choice_is_forwarded_to_linux_creation() -> None:
    linux = FakeLinux()

    result = UserProvisioner(linux, FakeSamba(True)).create(
        "alice", "secret", create_linux=True, create_home=True
    )

    assert result.ok
    assert linux.created == [("alice", True)]
