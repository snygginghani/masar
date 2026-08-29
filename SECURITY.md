# Security policy

## Supported version

Security fixes target the latest version on the default branch.

## Reporting a vulnerability

Do not publish active vulnerabilities or secrets in a public issue. Contact the repository maintainer privately through the security-reporting method configured on the GitHub repository. Include reproduction steps, impact, and a suggested fix when possible.

## Local security model

Masar is designed as a single-user application bound to `127.0.0.1`. Do not expose it directly to the public internet. API keys and SMTP credentials are held in process memory, but CVs, job records, and drafts are stored locally in `data/`. Protect the computer account and disk accordingly.

Before sharing a repository or diagnostic bundle, confirm that `data/`, `.env*`, uploaded CVs, database files, and screenshots with personal information are absent. If a key is ever committed or posted, revoke and replace it immediately; deleting it from the latest commit is not enough.
