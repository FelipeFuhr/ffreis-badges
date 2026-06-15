#!/usr/bin/env python3
"""Refresh shields.io endpoint JSON for every repo in manifest.json.

Why this exists: shields.io cannot read private repos (its servers query the
GitHub API unauthenticated). By having an authenticated poller write each repo's
status into THIS public repo, any repo — public or private — can embed a working
badge that points at the public raw JSON here.

Run by .github/workflows/refresh.yml (cron + workflow_dispatch) with a PAT that
has `repo` scope so it can read private repos' Actions runs and releases.

    GITHUB_TOKEN=<pat> python3 scripts/refresh_badges.py [--manifest manifest.json] [--out badges]

Each badge file is the shields.io endpoint schema:
    {"schemaVersion":1,"label":"...","message":"...","color":"..."}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"

# Primary CI workflow detection: first present (by filename) that has runs on the
# default branch wins. Override per repo via manifest "ci_workflow".
CI_WORKFLOW_PRIORITY = [
    "ci.yml", "devops-go-ci.yml", "tests.yml", "test.yml",
    "go-test.yml", "rust-test.yml", "python-test.yml",
    "build-all.yml", "android-ci.yml", "deploy.yml",
]

CONCLUSION_COLOR = {
    "success": "brightgreen",
    "failure": "red",
    "cancelled": "inactive",
    "timed_out": "red",
    "action_required": "yellow",
    "neutral": "lightgrey",
    "skipped": "lightgrey",
    "startup_failure": "red",
}

LICENSE_BADGE = {
    "AGPL-3.0": ("AGPL v3", "blue"),
    "MIT": ("MIT", "green"),
    "Apache-2.0": ("Apache 2.0", "blue"),
    "Proprietary": ("Proprietary", "red"),
    "other": ("see LICENSE", "lightgrey"),
}


def gh(path: str, token: str):
    """GET the GitHub API; return parsed JSON, or None on 404."""
    req = urllib.request.Request(API + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (403, 429) and attempt < 2:  # secondary rate limit
                time.sleep(5 * (attempt + 1))
                continue
            raise
    return None


def detect_ci_workflow(owner: str, repo: str, default_branch: str, token: str, override: str | None):
    candidates = [override] if override else []
    listing = gh(f"/repos/{owner}/{repo}/actions/workflows?per_page=100", token) or {}
    present = {os.path.basename(w["path"]) for w in listing.get("workflows", [])}
    candidates += [w for w in CI_WORKFLOW_PRIORITY if w in present]
    for wf in candidates:
        runs = gh(
            f"/repos/{owner}/{repo}/actions/workflows/{wf}/runs"
            f"?branch={default_branch}&per_page=1",
            token,
        )
        run_list = (runs or {}).get("workflow_runs") or []
        if run_list:
            return wf, run_list[0]
    return None, None


def ci_badge(owner: str, repo: str, default_branch: str, token: str, override: str | None) -> dict:
    _, run = detect_ci_workflow(owner, repo, default_branch, token, override)
    if not run:
        return {"schemaVersion": 1, "label": "CI", "message": "no runs", "color": "lightgrey"}
    state = run.get("conclusion") or run.get("status") or "unknown"
    msg = {"in_progress": "running", "queued": "queued"}.get(run.get("status"), state)
    return {
        "schemaVersion": 1,
        "label": "CI",
        "message": msg.replace("_", " "),
        "color": CONCLUSION_COLOR.get(state, "blue"),
    }


def version_badge(owner: str, repo: str, token: str) -> dict | None:
    rel = gh(f"/repos/{owner}/{repo}/releases/latest", token)
    tag = rel.get("tag_name") if rel else None
    if not tag:
        tags = gh(f"/repos/{owner}/{repo}/tags?per_page=1", token)
        tag = tags[0]["name"] if tags else None
    if not tag:
        return None  # unreleased -> omit the version badge entirely (no flooding)
    return {"schemaVersion": 1, "label": "version", "message": tag, "color": "blue"}


def license_badge(tier: str) -> dict | None:
    if tier == "none":
        return None
    label, color = LICENSE_BADGE.get(tier, LICENSE_BADGE["other"])
    return {"schemaVersion": 1, "label": "license", "message": label, "color": color}


def write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--out", default="badges")
    ap.add_argument("--only", help="comma-separated repo names (pilot subset)")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print("WARNING: no GITHUB_TOKEN/GH_TOKEN; private repos will be skipped", file=sys.stderr)

    manifest = json.load(open(args.manifest))
    owner = manifest["owner"]
    repos = manifest["repos"]
    if args.only:
        wanted = set(args.only.split(","))
        repos = [r for r in repos if r["name"] in wanted]

    index, errors = [], 0
    for r in repos:
        name = r["name"]
        outdir = os.path.join(args.out, name)
        try:
            ci = ci_badge(owner, name, r["default_branch"], token, r.get("ci_workflow"))
            write(os.path.join(outdir, "ci.json"), ci)
            ver = version_badge(owner, name, token)
            if ver:
                write(os.path.join(outdir, "version.json"), ver)
            lic = license_badge(r["license"])
            if lic:
                write(os.path.join(outdir, "license.json"), lic)
        except Exception as exc:  # one bad repo must not abort the whole refresh
            errors += 1
            print(f"ERROR {name}: {exc}", file=sys.stderr)
            continue
        index.append({
            "name": name, "visibility": r["visibility"],
            "ci": ci["message"], "version": (ver or {}).get("message", "-"),
            "license": r["license"],
        })
        print(f"{name:42} ci={ci['message']:12} ver={(ver or {}).get('message','-'):10} lic={r['license']}", file=sys.stderr)

    write(os.path.join(args.out, "index.json"), {"repos": index})
    print(f"# wrote badges for {len(index)} repos ({errors} errors)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
