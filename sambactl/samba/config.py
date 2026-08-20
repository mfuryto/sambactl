from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SECTION_RE = re.compile(r"^\s*\[([^]]+)]\s*(?:[#;].*)?$")
OPTION_RE = re.compile(r"^(\s*)([^#;\s][^=]*?)(\s*=\s*)(.*?)(\r?\n)?$")


@dataclass(frozen=True)
class Section:
    name: str
    start: int
    end: int


class SambaConfig:
    """A surgical, line-preserving smb.conf editor."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines(keepends=True)
        if text and not self.lines:
            self.lines = [text]

    @classmethod
    def read(cls, path: Path) -> SambaConfig:
        return cls(path.read_text(encoding="utf-8"))

    def render(self) -> str:
        return "".join(self.lines)

    def sections(self) -> list[Section]:
        found: list[tuple[str, int]] = []
        for index, line in enumerate(self.lines):
            match = SECTION_RE.match(line.rstrip("\r\n"))
            if match:
                found.append((match.group(1).strip(), index))
        return [
            Section(name, start, found[pos + 1][1] if pos + 1 < len(found) else len(self.lines))
            for pos, (name, start) in enumerate(found)
        ]

    def section(self, name: str) -> Section | None:
        return next((s for s in self.sections() if s.name.casefold() == name.casefold()), None)

    def share_names(self) -> list[str]:
        return [s.name for s in self.sections() if s.name.casefold() != "global"]

    def options(self, section_name: str) -> dict[str, str]:
        section = self.section(section_name)
        if not section:
            return {}
        values: dict[str, str] = {}
        for line in self.lines[section.start + 1 : section.end]:
            match = OPTION_RE.match(line)
            if match:
                values[match.group(2).strip()] = match.group(4).strip()
        return values

    def set_options(self, section_name: str, options: Mapping[str, str | None]) -> None:
        section = self.section(section_name)
        if not section:
            self._append_section(section_name, {k: v for k, v in options.items() if v is not None})
            return
        requested = {key.casefold(): (key, value) for key, value in options.items()}
        seen: set[str] = set()
        output: list[str] = []
        for line in self.lines[section.start + 1 : section.end]:
            match = OPTION_RE.match(line)
            normalized = match.group(2).strip().casefold() if match else None
            if normalized in requested:
                _, value = requested[normalized]
                seen.add(normalized)
                if value is not None:
                    newline = match.group(5) or "\n"
                    output.append(
                        f"{match.group(1)}{match.group(2).strip()}{match.group(3)}{value}{newline}"
                    )
            else:
                output.append(line)
        for normalized, (key, value) in requested.items():
            if normalized not in seen and value is not None:
                output.append(f"    {key} = {value}\n")
        self.lines[section.start + 1 : section.end] = output

    def rename_section(self, old_name: str, new_name: str) -> None:
        if old_name.casefold() != new_name.casefold() and self.section(new_name):
            raise ValueError(f"Section [{new_name}] already exists")
        section = self.section(old_name)
        if not section:
            raise KeyError(old_name)
        suffix = "\n" if self.lines[section.start].endswith("\n") else ""
        self.lines[section.start] = f"[{new_name}]{suffix}"

    def delete_section(self, name: str) -> None:
        section = self.section(name)
        if not section:
            raise KeyError(name)
        start = section.start
        if start and not self.lines[start - 1].strip():
            start -= 1
        del self.lines[start : section.end]

    def _append_section(self, name: str, options: Mapping[str, str]) -> None:
        if self.lines and self.lines[-1].strip():
            self.lines.append("\n")
        self.lines.append(f"[{name}]\n")
        self.lines.extend(f"    {key} = {value}\n" for key, value in options.items())


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
