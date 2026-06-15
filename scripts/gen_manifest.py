#!/usr/bin/env python3
"""Generate manifest.json: the fleet roster + per-repo static badge facts.

Source of truth for the badge poller. Static facts (license tier, visibility,
default branch) live here; dynamic facts (CI result, version) are fetched live
by refresh_badges.py. Regenerate when repos are added/removed or a license
changes:  python3 scripts/gen_manifest.py /path/to/workspace /tmp/repos2.json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# License tier detection from the first lines of a LICENSE file.
LICENSE_PATTERNS = [
    (re.compile(r"GNU AFFERO", re.I), "AGPL-3.0"),
    (re.compile(r"\bMIT License\b", re.I), "MIT"),
    (re.compile(r"Apache License", re.I), "Apache-2.0"),
    (re.compile(r"All Rights Reserved", re.I), "Proprietary"),
]

SKIP_PREFIXES = ("old/", "_orphaned/", ".worktrees/", ".workspaces/", ".git/")


def license_tier(repo_dir: str) -> str:
    path = os.path.join(repo_dir, "LICENSE")
    if not os.path.isfile(path):
        return "none"
    with open(path, encoding="utf-8", errors="replace") as fh:
        head = "".join(fh.readline() for _ in range(8))
    for pat, tier in LICENSE_PATTERNS:
        if pat.search(head):
            return tier
    return "other"


def remote_name(repo_dir: str) -> str | None:
    try:
        url = subprocess.check_output(
            ["git", "-C", repo_dir, "config", "--get", "remote.origin.url"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    if not url:
        return None
    return os.path.basename(url[:-4] if url.endswith(".git") else url)


def iter_repos(root: str):
    for dirpath, dirnames, _ in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel != "." and (rel + "/").startswith(SKIP_PREFIXES):
            dirnames[:] = []
            continue
        if ".git" in os.listdir(dirpath):
            yield dirpath
            dirnames[:] = []  # do not descend into a repo's submodules/vendored copies


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    gh_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/repos2.json"

    gh = {}
    with open(gh_path) as fh:
        for r in json.load(fh):
            if r.get("isArchived"):
                continue
            gh[r["name"]] = {
                "visibility": r["visibility"].lower(),
                "default_branch": (r.get("defaultBranchRef") or {}).get("name") or "main",
            }

    repos: dict[str, dict] = {}
    for repo_dir in iter_repos(root):
        name = remote_name(repo_dir)
        if not name or name not in gh:
            continue  # no remote, or not a FelipeFuhr repo (archived/fork)
        if name in repos:
            continue  # dedupe vendored/nested copies of the same GitHub repo
        repos[name] = {
            "name": name,
            "visibility": gh[name]["visibility"],
            "default_branch": gh[name]["default_branch"],
            "license": license_tier(repo_dir),
            "has_sonar": os.path.isfile(os.path.join(repo_dir, "sonar-project.properties")),
        }

    manifest = {
        "owner": "FelipeFuhr",
        "repos": [repos[k] for k in sorted(repos)],
    }
    json.dump(manifest, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.stderr.write(f"# manifest: {len(repos)} repos\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
