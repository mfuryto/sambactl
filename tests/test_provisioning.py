from sambactl.system.commands import CommandResult
from sambactl.system.users import UserProvisioner


class FakeLinux:
    def __init__(self, existed=False, delete_ok=True):
        self.existed = existed
        self.delete_ok = delete_ok
        self.created = []
        self.deleted = []

    def exists(self, username):
        return self.existed

    def create(self, username):
        self.created.append(username)
        return CommandResult(("useradd", username), 0)

    def delete(self, username):
        self.deleted.append(username)
        return CommandResult(("userdel", username), 0 if self.delete_ok else 1, stderr="denied")


class FakeSamba:
    def __init__(self, ok):
        self.ok = ok

    def create(self, username, password):
        return CommandResult(("smbpasswd", username), 0 if self.ok else 1, stderr="failed")


def test_new_linux_user_is_removed_if_samba_creation_fails() -> None:
    linux = FakeLinux()
    result = UserProvisioner(linux, FakeSamba(False)).create("alice", "secret", create_linux=True)
    assert not result.ok
    assert linux.created == ["alice"]
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
