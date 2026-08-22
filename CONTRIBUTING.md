# Contributing to Sambactl

Thank you for helping improve Sambactl.

## Standard workflow

1. Search existing issues before starting work.
2. Open an issue for bugs, feature requests, or material behavior changes.
3. Agree on scope before implementing a large or security-sensitive change.
4. Create a focused branch and reference the issue in commits and the pull
   request.
5. Add or update tests and documentation.
6. Open a pull request against `main` and complete the template.
7. Address review feedback and wait for all required CI checks.

Small documentation corrections may be submitted directly as a pull request,
but should still explain the reason for the change.

Security vulnerabilities must follow [SECURITY.md](SECURITY.md) and must not be
reported in public issues.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Before opening a pull request, run:

```bash
ruff check .
pytest --cov=sambactl
python -m build
```

Changes affecting Debian packaging should also pass:

```bash
dpkg-buildpackage -us -uc -b
```

## Pull request requirements

- Keep the change narrowly scoped.
- Link the relevant issue with `Fixes #...`, `Closes #...`, or `Refs #...`.
- Explain user-visible behavior, risks, and rollback considerations.
- Include tests for regressions and new behavior.
- Preserve compatibility with supported Debian and Ubuntu releases.
- Never include secrets, production data, password hashes, or unredacted logs.
- Do not merge with failing or pending required checks.

## Code expectations

- Support Python 3.10 and newer.
- Preserve Sambactl's validation, atomic-write, backup, reload, and rollback
  guarantees.
- Keep system-changing commands testable through the command runner.
- Prefer clear, focused code over broad abstractions.
- Maintain keyboard-only operation and compatibility with distribution-provided
  `prompt_toolkit` versions.

## Reporting bugs

Use the bug report form and include the Sambactl version, operating system,
Python version, Samba version, reproduction steps, expected result, and
redacted logs. Confirm the issue against the latest release when possible.
