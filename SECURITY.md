# Security Policy

Report vulnerabilities privately via GitHub's security advisory system:
https://github.com/FelipeFuhr/ffreis-badges/security/advisories/new

Response time: 5–7 business days.

## Scope note

This repository contains only **public status metadata** (CI result, latest
version, license tier) regenerated from the GitHub API. It holds no secrets and
no source code from the repos it mirrors. The refresh workflow reads private
repos through a least-privilege PAT (`BADGES_PAT`) that is never written to disk.
