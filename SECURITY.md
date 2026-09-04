# Security policy

> [!WARNING]
> Sambactl is archived, unsupported, and has been replaced by
> [UserDock](https://github.com/mfuryto/userdock). No Sambactl version receives
> security updates. Migrate to UserDock rather than deploying Sambactl on new
> systems.

## Supported versions

Security fixes are no longer provided for Sambactl.

| Version | Supported |
| --- | --- |
| 0.2.x | No |
| 0.1.x | No |
| Older versions | No |

## Reporting a vulnerability

Do not disclose suspected vulnerabilities in a public issue, discussion, pull
request, or other public channel.

Use GitHub's private vulnerability reporting for this repository:

https://github.com/mfuryto/sambactl/security/advisories/new

Include the affected version, operating system, Samba version, reproduction
steps, impact, and any proposed mitigation. Remove passwords, password hashes,
private configuration, hostnames, IP addresses, and other sensitive data.

The repository is retained for historical reference. Vulnerability reports may
be reviewed for awareness, but fixes and new Sambactl releases are not planned.

## Security expectations

- Never commit credentials, private keys, password hashes, or production
  `smb.conf` files.
- Use synthetic or redacted fixtures in tests and bug reports.
- Keep dependencies and GitHub Actions pinned to trusted upstream projects.
- Do not weaken validation, rollback, filesystem, or privilege boundaries
  without an explicit security review.
