#!/usr/bin/env python3
"""Print the curated badge block for a repo (markdown, idempotent markers).

Emits only the badges whose endpoint JSON actually exists under badges/<key>/,
so unreleased repos get no version badge and repos with no LICENSE get no license
badge — curated, never flooding. The markers let a README inject/replace the
block re-runnably.

Current (opaque id, no central lookup — see README.md "Opaque per-repo IDs"):
resolves the id straight from the target repo's OWN local checkout, nothing is
looked up by name here.

    python3 scripts/render_block.py --repo-dir /path/to/that/repo [--default-branch main]

Legacy (name-keyed, deprecated — kept only for the transition, see
MIGRATION.md): still works for a repo that hasn't been re-keyed by id yet.

    python3 scripts/render_block.py <repo-name> [--default-branch main]
"""

from __future__ import annotations

import argparse
import os

import badge_id
import gen_manifest

OWNER = "FelipeFuhr"
RAW = f"https://raw.githubusercontent.com/{OWNER}/ffreis-badges/main/badges"
START, END = "<!-- ffreis-badges:start -->", "<!-- ffreis-badges:end -->"

# metric -> (alt text, link target template using {owner}/{repo}/{branch})
LINKS = {
    "ci": ("CI", "https://github.com/{owner}/{repo}/actions"),
    "version": ("Latest version", "https://github.com/{owner}/{repo}/releases"),
    "license": ("License", "https://github.com/{owner}/{repo}/blob/{branch}/LICENSE"),
}
ORDER = ["ci", "version", "license"]


def render(repo: str, branch: str, badges_dir: str = "badges", *, key: str | None = None) -> str:
    """Render the curated block for `repo` (used only for the link hrefs,
    which point at that repo's own, already-public GitHub pages). `key` picks
    which badges/<key>/ dir to read endpoint files from and to build the
    published image URLs from — an opaque id in the current scheme, or (the
    legacy, name-keyed fallback) `repo` itself when `key` is omitted.
    """
    lookup_key = key if key is not None else repo
    lines = [START]
    for metric in ORDER:
        if not os.path.isfile(os.path.join(badges_dir, lookup_key, f"{metric}.json")):
            continue
        alt, link_tpl = LINKS[metric]
        img = f"https://img.shields.io/endpoint?url={RAW}/{lookup_key}/{metric}.json"
        link = link_tpl.format(owner=OWNER, repo=repo, branch=branch)
        lines.append(f"[![{alt}]({img})]({link})")
    lines.append(END)
    # badges on one line, separated by spaces, is the conventional README header
    return lines[0] + "\n" + " ".join(lines[1:-1]) + "\n" + lines[-1]


def render_from_repo_dir(repo_dir: str, branch: str, badges_dir: str = "badges") -> str:
    """Resolve the repo's real name (for link hrefs only) and its own opaque
    id (for the published image URLs) straight from ITS OWN local checkout —
    no central name->id lookup table, ever (see README.md).
    """
    name = gen_manifest.remote_name(repo_dir)
    if not name:
        raise SystemExit(
            f"error: {repo_dir} has no readable git remote — can't determine its repo name"
        )
    own_id = badge_id.read_id_from_dir(repo_dir)
    if not own_id:
        raise SystemExit(
            f"error: {repo_dir} has no {badge_id.ID_FILE_RELPATH} yet. Wait for "
            "the next scheduled poller run against this repo (it self-"
            "provisions one automatically), or ask for an out-of-band run — "
            "see MIGRATION.md."
        )
    return render(name, branch, badges_dir, key=own_id)


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "repo",
        nargs="?",
        default=None,
        help="legacy: repo name, looked up by name (deprecated — see MIGRATION.md)",
    )
    group.add_argument(
        "--repo-dir",
        help="path to the local checkout of the repo embedding the badges — "
        "reads that repo's own .github/badge-id, no name lookup",
    )
    ap.add_argument("--default-branch", default="main")
    ap.add_argument("--badges-dir", default="badges")
    args = ap.parse_args()

    if args.repo_dir:
        print(render_from_repo_dir(args.repo_dir, args.default_branch, args.badges_dir))
    else:
        print(render(args.repo, args.default_branch, args.badges_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
