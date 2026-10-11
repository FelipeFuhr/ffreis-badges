# ffreis-badges

<!-- ffreis-badges:start -->
[![CI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/89e0c647c309/ci.json)](https://github.com/FelipeFuhr/ffreis-badges/actions) [![License](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/89e0c647c309/license.json)](https://github.com/FelipeFuhr/ffreis-badges/blob/main/LICENSE)
<!-- ffreis-badges:end -->

Public **badge-data mirror** for the whole repo fleet. It exists to solve one
problem: shields.io cannot read private repos (its servers hit the GitHub API
unauthenticated), so a normal CI/version/coverage badge renders broken in a
private repo. This repo is **public**, so an authenticated poller can write each
repo's status here as a [shields.io endpoint][endpoint] JSON, and *any* repo —
public or private — can embed a badge that points at this public raw JSON.

## Opaque per-repo IDs (no name, no visibility, ever published)

Every file this repo *publishes* — `badges/<id>/*.json` and `badges/index.json`
— is keyed by an **opaque, random per-repo ID**, never by the repo's real name,
and never carries a `visibility` field. A name-keyed public index hands anyone
a complete, labeled roster of the owner's entire GitHub portfolio (that's
exactly what this repo used to publish — see [MIGRATION.md](MIGRATION.md) for
the full writeup). The ID carries no information about which repo it is, and
— unlike a hash of the name — isn't reversible by brute force.

Each repo stores its **own** ID in a file inside **itself**:

```
.github/badge-id      # one line, 12 lowercase hex chars, e.g. 89e0c647c309
```

There is **no central name→id table anywhere in this repo** — the poller reads
that file straight out of each repo it's polling (via the GitHub Contents
API), and a repo's own tooling reads the same file out of its own local
checkout. If a repo doesn't have one yet, the next scheduled poller run
self-provisions it (see "How it refreshes" below) — see
[MIGRATION.md](MIGRATION.md) for the transition plan and what's temporarily
still name-keyed.

## How a repo embeds its badges

Add the curated block to the top of the repo's `README.md`, generated from
**that repo's own local checkout** (it reads its own `.github/badge-id` —
nothing is looked up centrally by name):

```bash
python3 scripts/render_block.py --repo-dir /path/to/that/repo
```

```markdown
<!-- ffreis-badges:start -->
[![CI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/<id>/ci.json)](https://github.com/FelipeFuhr/<repo>/actions) [![License](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/FelipeFuhr/ffreis-badges/main/badges/<id>/license.json)](https://github.com/FelipeFuhr/<repo>/blob/main/LICENSE)
<!-- ffreis-badges:end -->
```

`<id>` is that repo's own opaque ID (image URLs — published here, must stay
anonymous); `<repo>` is its real name (link targets only — those just point at
the repo's own, already-public GitHub pages, so using the real name there
leaks nothing new).

The markers make the block re-runnable: a future rollout/refresh replaces what's
between them and leaves the rest of the README untouched.

**Legacy, name-keyed form** (deprecated — kept only so the ~110 READMEs still
embedding it keep rendering during the transition, see MIGRATION.md):
`python3 scripts/render_block.py <repo-name>` still works and still points at
`badges/<repo-name>/*.json`, which the poller keeps writing dual-key until the
fleet-wide README migration (tracked separately) is done.

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
Actions minutes are free on this public repo. It decodes the name-keyed roster
from the `BADGES_MANIFEST` secret into a local `manifest.json` (never
committed — see below), then runs
[`scripts/refresh_badges.py --provision-ids`](scripts/refresh_badges.py), which
reads every repo in that roster through `BADGES_PAT`, resolves (or
self-provisions) each repo's own `.github/badge-id`, and rewrites the endpoint
JSON under [`badges/`](badges/) — id-keyed, plus a legacy name-keyed copy for
the transition (see [MIGRATION.md](MIGRATION.md)).

### Required secrets

- `BADGES_PAT` — a fine-grained PAT with **read** access to *Actions*,
  *Contents*, and *Metadata* on all repos (including private). Without it the
  workflow falls back to `github.token`, which can only see this repo.
  **Self-provisioning `.github/badge-id` in a repo that doesn't have one yet
  additionally needs Contents:*write*** on that repo — `BADGES_PAT` is
  read-only today, so until its scope is widened, provisioning a missing ID
  is a safe per-repo no-op (logged, never fatal) rather than an error. See
  MIGRATION.md for why this is flagged as a judgment call rather than done
  unilaterally.
- `BADGES_MANIFEST` — the output of `scripts/gen_manifest.py` (see
  "Maintenance" below), stored as a secret instead of committed because it's
  name-keyed: `gh secret set BADGES_MANIFEST < manifest.json`.

## Maintenance

```bash
# Re-derive the fleet roster + license tiers after adding/removing a repo.
# This file is intentionally NOT committed (see .gitignore) — it names every
# repo in the fleet, including which ones are private.
python3 scripts/gen_manifest.py /path/to/workspace /tmp/repos.json > manifest.json
#   (repos.json = gh repo list FelipeFuhr --json name,visibility,defaultBranchRef,isArchived)

# Publish the regenerated roster to the poller (never commit it):
gh secret set BADGES_MANIFEST --repo FelipeFuhr/ffreis-badges < manifest.json

# Refresh all endpoint JSON locally (read-only against every OTHER repo —
# add --provision-ids only if you explicitly want this run to also create
# missing .github/badge-id files, which needs Contents:write there):
GH_TOKEN=$(gh auth token) python3 scripts/refresh_badges.py

# Print the badge block to paste into a repo's README — reads that repo's
# OWN .github/badge-id, no central lookup:
python3 scripts/render_block.py --repo-dir /path/to/that/repo

# Legacy, name-keyed form (deprecated, see MIGRATION.md):
python3 scripts/render_block.py <repo-name>
```

The current fleet snapshot is in [`badges/index.json`](badges/index.json) —
id-keyed only, no name, no visibility.

[endpoint]: https://shields.io/badges/endpoint-badge
