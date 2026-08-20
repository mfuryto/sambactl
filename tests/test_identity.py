import pytest

from sambactl.system.identity import parse_mode, validate_username


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
