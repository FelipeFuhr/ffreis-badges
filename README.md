# ffreis-badges

<!-- ffreis-badges:start -->
[![CI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/ffreis-badges/ci.json)](https://github.com/FelipeFuhr/ffreis-badges/actions) [![License](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/ffreis-badges/license.json)](https://github.com/FelipeFuhr/ffreis-badges/blob/main/LICENSE)
<!-- ffreis-badges:end -->

Public **badge-data mirror** for the whole repo fleet. It exists to solve one
problem: shields.io cannot read private repos (its servers hit the GitHub API
unauthenticated), so a normal CI/version/coverage badge renders broken in a
private repo. This repo is **public**, so an authenticated poller can write each
repo's status here as a [shields.io endpoint][endpoint] JSON, and *any* repo —
public or private — can embed a badge that points at this public raw JSON.

## How a repo embeds its badges

Add the curated block to the top of the repo's `README.md` (generate it with
`scripts/render_block.py <repo>`):

```markdown
<!-- ffreis-badges:start -->
[![CI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/<repo>/ci.json)](https://github.com/FelipeFuhr/<repo>/actions) [![License](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/<repo>/license.json)](https://github.com/FelipeFuhr/<repo>/blob/main/LICENSE)
<!-- ffreis-badges:end -->
```

The markers make the block re-runnable: a future rollout/refresh replaces what's
between them and leaves the rest of the README untouched.

## Curated badge set (never flooding)

Per repo, at most: **CI · version · license** — and a badge is emitted *only* when
it has data:

| Badge | Source | Shown when |
|---|---|---|
| **CI** | latest run of the primary CI workflow on the default branch | always (`no runs` if none) |
| **version** | latest release, else latest tag | repo actually has one (unreleased → omitted) |
| **license** | tier from the repo's `LICENSE` (manifest) | repo has a `LICENSE` |

CI status is honest: it mirrors the default branch's *actual* last result, so a
red badge means the build is really red.

## How it refreshes

[`.github/workflows/refresh.yml`](.github/workflows/refresh.yml) runs every 6h
(and on demand via `workflow_dispatch` / `repository_dispatch: refresh-badges`).
Actions minutes are free on this public repo. It runs
[`scripts/refresh_badges.py`](scripts/refresh_badges.py), which reads every repo
in [`manifest.json`](manifest.json) through `BADGES_PAT` and rewrites the endpoint
JSON under [`badges/`](badges/).

### Required secret

`BADGES_PAT` — a fine-grained PAT with **read** access to *Actions*, *Contents*,
and *Metadata* on all repos (including private). Without it the workflow falls
back to `github.token`, which can only see this repo.

## Maintenance

```bash
# Re-derive the fleet roster + license tiers after adding/removing a repo:
python3 scripts/gen_manifest.py /path/to/workspace /tmp/repos.json > manifest.json
#   (repos.json = gh repo list FelipeFuhr --json name,visibility,defaultBranchRef,isArchived)

# Refresh all endpoint JSON locally (read-only against GitHub):
GH_TOKEN=$(gh auth token) python3 scripts/refresh_badges.py

# Print the badge block to paste into a repo's README:
python3 scripts/render_block.py <repo>
```

The current fleet snapshot is in [`badges/index.json`](badges/index.json).

[endpoint]: https://shields.io/badges/endpoint-badge
