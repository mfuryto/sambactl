from pathlib import Path

from conftest import FakeRunner

from sambactl.models import ShareFilesystemPlan, Status
from sambactl.samba.config import SambaConfig
from sambactl.samba.service import SambaServiceManager
from sambactl.samba.shares import ShareManager
from sambactl.samba.validation import Validator
from sambactl.system.commands import CommandResult


def test_validation_success(config_path: Path) -> None:
    runner = FakeRunner()
    report = Validator(runner, SambaServiceManager(runner)).syntax(
        config_path.read_text(), config_path.parent
    )
    assert report.status == Status.READY


def test_missing_testparm_fails(config_path: Path) -> None:
    runner = FakeRunner(fail={"testparm"})
    report = Validator(runner, SambaServiceManager(runner)).syntax(
        config_path.read_text(), config_path.parent
    )
    assert report.status == Status.FAILED


def test_validation_tempfile_failure_is_reported(config_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sambactl.samba.validation.tempfile.mkstemp",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no temp space")),
    )
    report = Validator(FakeRunner(), SambaServiceManager(FakeRunner())).syntax(
        config_path.read_text(), config_path.parent
    )
    assert report.status == Status.FAILED
    assert "no temp space" in report.checks[0].detail


def test_dry_run_reports_missing_share_path(config_path: Path) -> None:
    runner = FakeRunner()
    report = Validator(runner, SambaServiceManager(runner)).dry_run(config_path)
    assert report.status == Status.WARNING
    assert any("does not exist" in check.detail for check in report.checks)


def test_share_operation_preflight_checks_filesystem_and_identities(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    validator = Validator(runner, SambaServiceManager(runner))
    proposed = SambaConfig.read(config_path)
    share_path = tmp_path / "new-share"
    values = {"path": str(share_path), "valid users": "alice", "write list": "@editors"}
    ShareManager.create(proposed, "new", values)
    identity = type("Identity", (), {"id": 1000})()
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: identity)
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: identity)

    report = validator.preflight_share(
        config_path,
        proposed.render(),
        ShareFilesystemPlan(share_path, "alice", "editors", 0o2770),
        values,
    )

    assert report.ok
    assert not share_path.exists()
    names = {check.name for check in report.checks}
    assert {"Directory owner", "Directory group", "Directory mode"} <= names
    assert "valid users: alice" in names
    assert "write list: @editors" in names


def test_share_preflight_rejects_missing_group(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    validator = Validator(runner, SambaServiceManager(runner))
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: object())
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: None)
    report = validator.preflight_share(
        config_path,
        config_path.read_text(),
        ShareFilesystemPlan(tmp_path / "share", "alice", "missing", 0o2770),
        {"path": str(tmp_path / "share")},
    )
    assert report.status == Status.FAILED
    assert any(check.name == "Directory group" for check in report.checks)


def test_proposed_config_rejected_by_testparm(config_path: Path) -> None:
    class RejectingRunner(FakeRunner):
        def run(self, args, **kwargs):
            argv = tuple(str(arg) for arg in args)
            if argv[0] == "testparm":
                return CommandResult(argv, 1, stderr="syntax error")
            return super().run(argv, **kwargs)

    report = Validator(RejectingRunner(), SambaServiceManager(RejectingRunner())).syntax(
        "[broken", config_path.parent
    )
    assert report.status == Status.FAILED
    assert report.checks[0].detail == "syntax error"
    assert list(config_path.parent.glob(".sambactl-validate-*")) == []


def test_dry_run_reports_missing_commands_and_unavailable_service(config_path: Path) -> None:
    runner = FakeRunner(fail={"systemctl"})
    report = Validator(runner, SambaServiceManager(runner)).dry_run(config_path)
    assert report.status == Status.FAILED
    assert any(check.name == "Required command: systemctl" for check in report.checks)
    assert any(
        check.name == "Samba service" and check.status == Status.FAILED for check in report.checks
    )


def test_service_without_reload_capability_fails(config_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    services = SambaServiceManager(runner)
    monkeypatch.setattr(services, "can_reload", lambda: (False, "reload unsupported"))
    report = Validator(runner, services).dry_run(config_path)
    assert any(
        check.name == "Reload capability" and check.status == Status.FAILED
        for check in report.checks
    )


def test_inaccessible_share_path_is_reported(
    config_path: Path, tmp_path: Path, monkeypatch
) -> None:
    share = tmp_path / "share"
    share.mkdir()
    config = SambaConfig.read(config_path)
    config.set_options("docs", {"path": str(share)})
    config_path.write_text(config.render())
    real_access = __import__("os").access
    monkeypatch.setattr(
        "sambactl.samba.validation.os.access",
        lambda path, mode: False if Path(path) == share else real_access(path, mode),
    )
    report = Validator(FakeRunner(), SambaServiceManager(FakeRunner())).dry_run(config_path)
    assert any("is not accessible" in check.detail for check in report.checks)


def test_unwritable_config_and_backup_locations_fail(config_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("sambactl.samba.validation.os.access", lambda path, mode: False)
    report = Validator(FakeRunner(), SambaServiceManager(FakeRunner())).dry_run(config_path)
    failures = {check.name for check in report.checks if check.status == Status.FAILED}
    assert "Atomic write access" in failures
    assert "Backup directory" in failures


def test_preflight_rejects_missing_user_group_pdbedit_and_world_write(
    config_path: Path, tmp_path: Path, monkeypatch
) -> None:
    runner = FakeRunner(fail={"pdbedit"})
    validator = Validator(runner, SambaServiceManager(runner))
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: None)
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: None)
    values = {"path": str(tmp_path / "share"), "valid users": "missing"}
    report = validator.preflight_share(
        config_path,
        config_path.read_text(),
        ShareFilesystemPlan(tmp_path / "share", "missing", "missing", 0o777),
        values,
    )
    failed = {check.name for check in report.checks if check.status == Status.FAILED}
    assert "Directory owner" in failed
    assert "Directory group" in failed
    assert "Directory mode" in failed
    assert "Required command: pdbedit" in failed


def test_dry_run_rejects_non_directory_share(tmp_path: Path) -> None:
    share = tmp_path / "not-a-directory"
    share.write_text("data")
    config_path = tmp_path / "smb.conf"
    config_path.write_text(f"[global]\n[bad]\n path = {share}\n")
    report = Validator(FakeRunner(), SambaServiceManager(FakeRunner())).dry_run(config_path)
    assert any(
        check.name == "Share [bad] path" and check.status == Status.FAILED
        for check in report.checks
    )


def test_preflight_rejects_symlink_and_regular_file_share_targets(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    identity = type("Identity", (), {"id": 1000})()
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: identity)
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: identity)
    validator = Validator(FakeRunner(), SambaServiceManager(FakeRunner()))
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    regular = tmp_path / "file"
    regular.write_text("data")
    for target in (link, regular):
        report = validator.preflight_share(
            config_path,
            config_path.read_text(),
            ShareFilesystemPlan(target, "alice", "editors", 0o2770),
            {"path": str(target)},
        )
        assert any(
            check.name == "Target path" and check.status == Status.FAILED for check in report.checks
        )


def test_preflight_reports_metadata_change_and_invalid_reference(
    monkeypatch, config_path: Path, tmp_path: Path
) -> None:
    share = tmp_path / "share"
    share.mkdir(mode=0o700)
    identity = type("Identity", (), {"id": 99999})()
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: identity)
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: identity)
    report = Validator(FakeRunner(), SambaServiceManager(FakeRunner())).preflight_share(
        config_path,
        config_path.read_text(),
        ShareFilesystemPlan(share, "alice", "editors", 0o2770),
        {"path": str(share), "valid users": "--unsafe"},
    )
    assert any(check.name == "Directory metadata change" for check in report.checks)
    assert any("invalid account reference" in check.detail for check in report.checks)


def test_backup_path_that_is_a_file_is_not_ready(config_path: Path) -> None:
    backup_path = config_path.parent / "backups"
    backup_path.write_text("not a directory")
    report = Validator(FakeRunner(), SambaServiceManager(FakeRunner())).dry_run(config_path)
    assert any(
        check.name == "Backup directory" and check.status == Status.FAILED
        for check in report.checks
    )


def test_unsafe_config_target_and_unwritable_new_share_parent_fail(
    config_path: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "sambactl.samba.validation.resolved_regular_file",
        lambda path: (_ for _ in ()).throw(OSError("unsafe target")),
    )
    monkeypatch.setattr("sambactl.samba.validation.os.access", lambda path, mode: False)
    identity = type("Identity", (), {"id": 1000})()
    monkeypatch.setattr("sambactl.samba.validation.lookup_user", lambda name: identity)
    monkeypatch.setattr("sambactl.samba.validation.lookup_group", lambda name: identity)
    validator = Validator(FakeRunner(), SambaServiceManager(FakeRunner()))
    report = validator.preflight_share(
        config_path,
        config_path.read_text(),
        ShareFilesystemPlan(tmp_path / "missing" / "share", "alice", "editors", 0o2770),
        {},
    )
    assert any(check.name == "Configuration target" for check in report.checks)
    assert any(
        check.name == "Target path" and check.status == Status.FAILED for check in report.checks
    )
