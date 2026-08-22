# Security policy

## Supported versions

Security fixes are provided for the latest published release.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Older versions | No |

## Reporting a vulnerability

Do not disclose suspected vulnerabilities in a public issue, discussion, pull
request, or other public channel.

Use GitHub's private vulnerability reporting for this repository:

https://github.com/mfuryto/sambactl/security/advisories/new

Include the affected version, operating system, Samba version, reproduction
steps, impact, and any proposed mitigation. Remove passwords, password hashes,
private configuration, hostnames, IP addresses, and other sensitive data.

Reports will be acknowledged as soon as practical. Confirmed vulnerabilities
will be investigated privately, fixed on a restricted branch, and disclosed
through a GitHub Security Advisory when a safe release is available.

## Security expectations

- Never commit credentials, private keys, password hashes, or production
  `smb.conf` files.
- Use synthetic or redacted fixtures in tests and bug reports.
- Keep dependencies and GitHub Actions pinned to trusted upstream projects.
- Do not weaken validation, rollback, filesystem, or privilege boundaries
  without an explicit security review.
