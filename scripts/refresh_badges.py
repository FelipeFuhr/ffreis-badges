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

Opaque IDs (see badge_id.py / README.md "Opaque per-repo IDs"): manifest.json
is name-keyed (it has to be — the GitHub API only understands owner/repo, not
our own opaque IDs) but manifest.json is NOT committed to this public repo
(see .gitignore + MIGRATION.md); it only ever exists locally or decoded from
the BADGES_MANIFEST secret inside a CI run. The only PUBLIC, committed
artifacts this script writes are the files under `badges/`, and those are
keyed by opaque ID (plus, during the transition, legacy name-keyed copies —
see MIGRATION.md). Each repo's ID is resolved by reading `.github/badge-id`
straight out of THAT repo via the Contents API — self-provisioning a fresh
one there with --provision-ids if it's missing and the token can write it.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import badge_id

API = "https://api.github.com"

# Primary CI workflow detection: first present (by filename) that has runs on the
# default branch wins. Override per repo via manifest "ci_workflow".
CI_WORKFLOW_PRIORITY = [
    "ci.yml",
    "devops-go-ci.yml",
    "tests.yml",
    "test.yml",
    "go-test.yml",
    "rust-test.yml",
    "python-test.yml",
    "build-all.yml",
    "android-ci.yml",
    "deploy.yml",
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


def gh(path: str, token: str) -> Any:
    """GET the GitHub API; return parsed JSON (dict or list), or None on 404."""
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


def detect_ci_workflow(
    owner: str, repo: str, default_branch: str, token: str, override: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    candidates = [override] if override else []
    listing = gh(f"/repos/{owner}/{repo}/actions/workflows?per_page=100", token) or {}
    present = {os.path.basename(w["path"]) for w in listing.get("workflows", [])}
    candidates += [w for w in CI_WORKFLOW_PRIORITY if w in present]
    for wf in candidates:
        runs = gh(
            f"/repos/{owner}/{repo}/actions/workflows/{wf}/runs?branch={default_branch}&per_page=1",
            token,
        )
        run_list = (runs or {}).get("workflow_runs") or []
        if run_list:
            return wf, run_list[0]
    return None, None


def ci_badge(
    owner: str, repo: str, default_branch: str, token: str, override: str | None
) -> dict[str, Any]:
    _, run = detect_ci_workflow(owner, repo, default_branch, token, override)
    if not run:
        return {"schemaVersion": 1, "label": "CI", "message": "no runs", "color": "lightgrey"}
    status = run.get("status")
    state = str(run.get("conclusion") or status or "unknown")
    in_flight_labels = {"in_progress": "running", "queued": "queued"}
    msg = in_flight_labels.get(str(status), state) if status is not None else state
    return {
        "schemaVersion": 1,
        "label": "CI",
        "message": msg.replace("_", " "),
        "color": CONCLUSION_COLOR.get(state, "blue"),
    }


def version_badge(owner: str, repo: str, token: str) -> dict[str, Any] | None:
    rel = gh(f"/repos/{owner}/{repo}/releases/latest", token)
    tag = rel.get("tag_name") if rel else None
    if not tag:
        tags = gh(f"/repos/{owner}/{repo}/tags?per_page=1", token)
        tag = tags[0]["name"] if tags else None
    if not tag:
        return None  # unreleased -> omit the version badge entirely (no flooding)
    return {"schemaVersion": 1, "label": "version", "message": tag, "color": "blue"}


def license_badge(tier: str) -> dict[str, Any] | None:
    if tier == "none":
        return None
    label, color = LICENSE_BADGE.get(tier, LICENSE_BADGE["other"])
    return {"schemaVersion": 1, "label": "license", "message": label, "color": color}


def get_badge_id(owner: str, repo: str, token: str) -> str | None:
    """Fetch & validate `repo`'s own opaque id via the Contents API.

    None if the file is missing (404) or its content doesn't match
    badge_id.ID_PATTERN — never trust an unvalidated value into a public
    file path.
    """
    data = gh(f"/repos/{owner}/{repo}/contents/{badge_id.ID_FILE_RELPATH}", token)
    if not data or "content" not in data:
        return None
    try:
        raw = base64.b64decode(data["content"]).decode("utf-8", "replace").strip()
    except (ValueError, binascii.Error):
        return None
    return raw if badge_id.ID_PATTERN.match(raw) else None


def provision_badge_id(owner: str, repo: str, token: str) -> str | None:
    """Create `.github/badge-id` in `repo` via the Contents API.

    Requires Contents:write on THAT repo (BADGES_PAT is documented read-only
    today — see README "Required secrets"). Returns the new id on success;
    None if the token can't write there (403/404: no access; 422: the file
    already exists, a benign race with another concurrent run or a human) —
    the caller logs and skips that repo rather than inventing a workaround
    that needs broader fleet-wide permissions.
    """
    new_id = badge_id.generate_id()
    payload = json.dumps(
        {
            "message": "chore: provision opaque badge id",
            "content": base64.b64encode((new_id + "\n").encode("utf-8")).decode("ascii"),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/contents/{badge_id.ID_FILE_RELPATH}",
        data=payload,
        method="PUT",
    )
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30):
            return new_id
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404, 422):
            return None  # no write access on this repo, or someone else just created it
        raise


def resolve_badge_id(owner: str, repo: str, token: str, *, provision: bool) -> str | None:
    """`repo`'s own opaque id, self-provisioning a fresh one if missing and
    `provision` is set. `provision` defaults to False at the CLI so a local,
    ad-hoc refresh (README's "read-only against GitHub" preview command)
    never has the surprising side effect of writing to other repos; only the
    scheduled poller (.github/workflows/refresh.yml) passes --provision-ids.
    """
    existing = get_badge_id(owner, repo, token)
    if existing or not provision:
        return existing
    return provision_badge_id(owner, repo, token)


def write(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--out", default="badges")
    ap.add_argument("--only", help="comma-separated repo names (pilot subset)")
    ap.add_argument(
        "--provision-ids",
        action="store_true",
        help=(
            "self-provision .github/badge-id in repos that don't have one yet "
            "(requires the token to have Contents:write there — see README). "
            "Off by default so an ad-hoc local run stays read-only."
        ),
    )
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print("WARNING: no GITHUB_TOKEN/GH_TOKEN; private repos will be skipped", file=sys.stderr)

    # scan-fix(ruff:SIM115): open() as a context manager, not a bare call.
    with open(args.manifest) as fh:
        manifest = json.load(fh)
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

        # Opaque-id-keyed copy (the only form that will be left standing once
        # the fleet-wide README migration — tracked separately — is done; see
        # MIGRATION.md). Resolution/provisioning failures are never fatal:
        # this repo still gets its legacy name-keyed files above, it just
        # stays out of the new badges/<id>/ tree and index.json until it has
        # an id.
        resolved_id = None
        try:
            resolved_id = resolve_badge_id(owner, name, token, provision=args.provision_ids)
        except Exception as exc:
            print(f"WARNING {name}: badge-id resolution failed: {exc}", file=sys.stderr)

        if resolved_id:
            id_outdir = os.path.join(args.out, resolved_id)
            write(os.path.join(id_outdir, "ci.json"), ci)
            if ver:
                write(os.path.join(id_outdir, "version.json"), ver)
            if lic:
                write(os.path.join(id_outdir, "license.json"), lic)
            index.append(
                {
                    "id": resolved_id,
                    "ci": ci["message"],
                    "version": (ver or {}).get("message", "-"),
                    "license": r["license"],
                }
            )
        else:
            print(
                f"WARNING {name}: no badge-id file and could not provision one "
                "(no write access there yet, or --provision-ids wasn't passed) "
                "— omitted from the id-keyed badges/index.json until it has one",
                file=sys.stderr,
            )

        version_message = (ver or {}).get("message", "-")
        print(
            f"{name:42} ci={ci['message']:12} ver={version_message:10} "
            f"lic={r['license']:12} id={resolved_id or 'MISSING'}",
            file=sys.stderr,
        )

    write(os.path.join(args.out, "index.json"), {"repos": index})
    print(f"# wrote badges for {len(repos) - errors} repos ({errors} errors)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
