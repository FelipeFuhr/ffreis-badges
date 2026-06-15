#!/usr/bin/env python3
"""Print the curated badge block for a repo (markdown, idempotent markers).

Emits only the badges whose endpoint JSON actually exists under badges/<repo>/,
so unreleased repos get no version badge and repos with no LICENSE get no license
badge — curated, never flooding. The markers let a README inject/replace the
block re-runnably.

    python3 scripts/render_block.py <repo-name> [--default-branch main]
"""
from __future__ import annotations

import argparse
import os

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


def render(repo: str, branch: str, badges_dir: str = "badges") -> str:
    lines = [START]
    for metric in ORDER:
        if not os.path.isfile(os.path.join(badges_dir, repo, f"{metric}.json")):
            continue
        alt, link_tpl = LINKS[metric]
        img = f"https://img.shields.io/endpoint?url={RAW}/{repo}/{metric}.json"
        link = link_tpl.format(owner=OWNER, repo=repo, branch=branch)
        lines.append(f"[![{alt}]({img})]({link})")
    lines.append(END)
    # badges on one line, separated by spaces, is the conventional README header
    return lines[0] + "\n" + " ".join(lines[1:-1]) + "\n" + lines[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--default-branch", default="main")
    ap.add_argument("--badges-dir", default="badges")
    args = ap.parse_args()
    print(render(args.repo, args.default_branch, args.badges_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
