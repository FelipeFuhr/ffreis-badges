#!/usr/bin/env python3
"""Opaque per-repo badge-ID helpers, shared by gen_manifest.py, refresh_badges.py
and render_block.py.

Why an opaque ID instead of the repo name: badges/index.json and the per-repo
endpoint JSON under badges/ are PUBLIC (that's the whole point of this repo).
Keying them by real repo name publishes a complete, named roster of the
owner's entire GitHub portfolio, including which repos are private. The ID is
a random token, NOT derived from the name -- a deterministic hash (e.g.
sha256(name)) would be reversible by brute force over the small, guessable
universe of plausible repo names, which defeats the point entirely.

Each repo stores its OWN id in a file at ID_FILE_RELPATH inside ITS OWN
checkout -- never in a name->id table committed anywhere in this repo. See
README.md and MIGRATION.md for the full scheme and transition plan.
"""

from __future__ import annotations

import os
import re
import secrets

# One line, 12 lowercase hex chars (secrets.token_hex(6) -- 48 bits). Not a
# cryptographic secret, just non-guessable enough that nobody can map an ID
# back to a repo name by brute force or by trying plausible names.
ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
ID_FILE_RELPATH = os.path.join(".github", "badge-id")


def generate_id() -> str:
    """A fresh, random, non-deterministic opaque ID.

    Never derive this from the repo name (e.g. a hash) -- a deterministic
    mapping is reversible by brute force and defeats the purpose of the ID.
    """
    return secrets.token_hex(6)


def read_id_from_dir(repo_dir: str) -> str | None:
    """Read & validate the badge ID from a repo's LOCAL checkout.

    None if the file is missing, empty, or doesn't match ID_PATTERN -- never
    trust an unvalidated value into a public file path.
    """
    path = os.path.join(repo_dir, ID_FILE_RELPATH)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        candidate = fh.readline().strip()
    return candidate if ID_PATTERN.match(candidate) else None


def write_id_to_dir(repo_dir: str, badge_id: str) -> None:
    """Write a (freshly generated) ID file into a repo's LOCAL checkout.

    The caller is responsible for committing/pushing it from that repo --
    this never touches git, it only writes the one file.
    """
    path = os.path.join(repo_dir, ID_FILE_RELPATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(badge_id + "\n")
