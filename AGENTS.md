# Agent Context

**This repo:** `ffreis-badges` — a public **badge-data mirror** for the whole
repo fleet. Solves shields.io not being able to read private repos: an
authenticated poller (`scripts/refresh_badges.py`) writes each repo's CI/
version/license status here as shields.io endpoint JSON, so any repo — public
or private — can embed a working badge pointing at this public raw JSON. Full
design in `README.md`.

## Structure

```
scripts/gen_manifest.py      ← regenerates manifest.json (fleet roster + license tiers)
scripts/refresh_badges.py    ← polls GitHub API, writes badges/<repo>/{ci,version,license}.json
scripts/render_block.py      ← renders the curated <!-- ffreis-badges:start --> README block
manifest.json                ← committed fleet roster (source of truth for the poller)
badges/                      ← committed, generated shields.io endpoint JSON (do not hand-edit)
tests/                       ← pytest suite covering the three scripts above
```

## Judgment: right-sized CI, not full onboarding

This repo was evaluated against the fleet's 75% coverage + mutation-testing
initiative and deliberately given **lighter** treatment than a typical
service repo:

- **~340 lines total, zero runtime dependencies** (stdlib only: `json`, `os`,
  `re`, `subprocess`, `urllib`, `argparse`). Not a single trivial script, but
  not a service either — three small, independently-testable CLI scripts.
- **Coverage: yes, at the fleet's 75% floor** — `gen_manifest.license_tier()`,
  `iter_repos()`, `refresh_badges.ci_badge()`/`version_badge()`/
  `license_badge()`, and `render_block.render()` are real logic worth
  protecting (a regression here silently mis-badges the whole fleet), so they
  get a real pytest suite (`tests/`) with network/subprocess calls mocked.
- **No mutation testing.** Mutmut wiring + threshold tuning + a scheduled CI
  job is infrastructure overhead disproportionate to this repo's size and
  blast radius (a badge rendering wrong is cosmetic, not a production
  incident). The coverage floor is the meaningful safety net here.
- **No `coverage.yml` (Codecov upload).** Not worth a second workflow for a
  340-line utility; `make coverage`'s terminal report is sufficient locally
  and in CI.
- **lefthook**: only the shared `base.yml` tier (secret-scan, hygiene) plus a
  local `fmt-check` pre-commit hook and `quality-gates` pre-push hook — not
  the full `python.yml` remote tier (which expects `make mutation` /
  `make integration-coverage-gate` targets this repo has no use for).

Re-evaluate if this repo grows real integration surface (e.g. it starts
calling multiple external services beyond the GitHub API, or the poller logic
gets meaningfully more complex).

## Non-obvious facts

- **Package manager: `uv`** — `[tool.uv] package = false` in `pyproject.toml`
  because this is a scripts-only repo (no `src/` layout, no console entry
  points) — uv manages the dev dependency group only, never tries to build/
  install the project itself.
- **`scripts/*.py` are imported directly in tests** (not a package) —
  `tests/conftest.py` inserts `scripts/` onto `sys.path`.
- **`manifest.json` and `badges/` are committed, generated artifacts.**
  Regenerate `manifest.json` with `scripts/gen_manifest.py`, not by hand.
- **Required secret for the real poller**: `BADGES_PAT` (fine-grained PAT,
  read access to Actions + Contents + Metadata on all repos, including
  private). Falls back to `github.token`, which only sees this repo. This is
  unrelated to `ci.yml`'s test suite, which mocks all network calls.

## Build, run, test

```bash
make setup       # install lefthook git hooks + uv sync
make fmt         # ruff format
make fmt-check   # ruff format --check
make lint        # ruff check + mypy
make coverage    # pytest with the 75% gate
```

## Keeping this file current

- **If you add new dependencies:** run `uv add <pkg>` (updates pyproject.toml
  + uv.lock).
- **If you discover a fact not reflected here:** add it before finishing your
  task.
