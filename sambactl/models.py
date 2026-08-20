from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    READY = "READY"
    WARNING = "WARNING"
    FAILED = "FAILED"


@dataclass
class Check:
    name: str
    status: Status
    detail: str


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if any(c.status == Status.FAILED for c in self.checks):
            return Status.FAILED
        if any(c.status == Status.WARNING for c in self.checks):
            return Status.WARNING
        return Status.READY

    @property
    def ok(self) -> bool:
        return self.status != Status.FAILED


@dataclass
class RuntimeInfo:
    config_path: Path
    samba_version: str = "Unknown"
    services: list[str] = field(default_factory=list)
    service_mode: str = "Unavailable"
    missing_commands: list[str] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)


@dataclass
class OperationResult:
    ok: bool
    message: str
    report: ValidationReport | None = None


@dataclass(frozen=True)
class ShareFilesystemPlan:
    path: Path
    owner: str
    group: str
    mode: int
