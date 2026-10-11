# Migration: name-keyed → opaque-ID-keyed badges

## What was wrong

This repo is public (it has to be — that's the whole point, see README.md).
Until this change, both `manifest.json` (committed) and `badges/index.json`
(committed, generated) listed every repo in the fleet **by its real name**,
with `manifest.json` additionally carrying a `"visibility": "private"|"public"`
field per repo. Anyone could read either file straight off
`raw.githubusercontent.com` and get a complete, labeled inventory of the
owner's ~110-repo GitHub portfolio, including exactly which repos are private.
That is the actual bug this change fixes — not a style preference.

## What changed

- Every file this repo **publishes** is now keyed by a random, opaque,
  non-deterministic per-repo ID (`.github/badge-id` in the repo itself — see
  README.md "Opaque per-repo IDs"). `badges/<id>/*.json` and the new
  `badges/index.json` schema carry no `name` and no `visibility`, full stop.
- `manifest.json` — the poller's name-keyed input, which needed the real name
  all along to call the GitHub API by `owner/repo` — is no longer committed.
  It's generated locally exactly as before (`scripts/gen_manifest.py`), then
  published to the `BADGES_MANIFEST` GitHub Actions secret instead of to a
  tracked file (`.gitignore` now excludes it; `git rm --cached` removed it
  from the tree in this PR). A secret is the right tier for this — it's the
  same trust boundary `BADGES_PAT` already sits at, and anyone who could read
  `BADGES_PAT`'s value already implicitly has this same information via the
  API anyway, so this adds no new exposure beyond what already existed.
- `scripts/refresh_badges.py` resolves each repo's ID via the GitHub Contents
  API (`GET .github/badge-id` in that repo) and, when run with
  `--provision-ids` (which the scheduled workflow now always passes), creates
  one there if it's missing (`PUT .github/badge-id`) — self-provisioning, so
  no one has to hand-edit 110 repos to seed IDs. A repo that can't be written
  to yet is logged and skipped, never crashes the run, and simply has no
  id-keyed badges until it's provisioned on a later run.
- `scripts/render_block.py` gained `--repo-dir <path>`: it reads the ID (and,
  for the link hrefs only, the real name) straight out of that repo's own
  local checkout — no more `<repo-name>` argument that gets looked up in a
  central table. The old `<repo-name>` positional form still works (see
  "Transition plan" below).

## Why dual-write, not a hard cutover

~110 repos' READMEs already embed `<img>` tags pointing at
`badges/<real-name>/ci.json` etc. Cutting those files over immediately would
leave every one of those badges broken (404/stale) until someone edits all
110 READMEs. **Chosen approach: dual-write.** `refresh_badges.py` keeps
writing the legacy `badges/<name>/*.json` files (unchanged — exactly the same
exposure as before, not a regression, since removing them wouldn't remove the
fact that the name is public knowledge via a working repo link, only via this
specific pre-generated bundle of files) *in addition to* the new
`badges/<id>/*.json` files, for as long as any README still embeds the old
URL. This was judged safer than a hard cutover that breaks ~110 READMEs' badge
images the moment this PR merges, for a problem (the aggregate index/manifest
leak) that dual-writing the per-repo files doesn't make any worse.

`badges/index.json` (the aggregate fleet snapshot) is **not** dual-written —
nothing consumes its exact shape via automation (confirmed: grepped the whole
workspace for any reference to `ffreis-badges/manifest.json` or
`badges/index.json` outside this repo's own README; found none), so there's
no broken-URL risk in cutting it over immediately. It now ships as
`{"repos": []}` and fills back in, id-keyed, as the scheduled poller
provisions each repo.

## What the later, separate fleet-wide migration needs to do

Out of scope for this change (by design — see the task that produced this
PR): editing the ~110 consuming repos' own READMEs. When that follow-up runs,
per repo:

1. Confirm the repo has a `.github/badge-id` (the poller should have
   self-provisioned one on an earlier scheduled run by then — if not, run
   `refresh_badges.py --only <repo> --provision-ids` once by hand first).
2. Regenerate that repo's badge block with
   `python3 scripts/render_block.py --repo-dir /path/to/that/repo` and paste
   it between that repo's own `<!-- ffreis-badges:start/end -->` markers.
3. Once **every** repo's README has been confirmed migrated off the legacy
   URL, delete the dual-write code path in `refresh_badges.py` (the
   `outdir = os.path.join(args.out, name)` block and its writes) and the
   now-unused legacy `badges/<name>/` directories, and remove the deprecated
   `<repo-name>` positional mode from `render_block.py`.

Until step 3, badges render correctly either way — old or new embed — so
there's no forced ordering across the 110 repos; they can be migrated one at
a time, in any order, on any schedule.

## Judgment calls flagged for sign-off (not resolved unilaterally in this PR)

1. **`BADGES_PAT`'s scope.** It's documented read-only (Actions + Contents +
   Metadata, read). Self-provisioning `.github/badge-id` needs Contents:write
   on every fleet repo too. I did not request or assume that broader scope —
   fine-grained PAT permissions are a GitHub-side, owner-only action
   (github.com/settings/tokens), and widening a single token's write access
   across ~110 repos (one of them private) is a real increase in that
   token's blast radius if it's ever compromised, not something to wave
   through silently. Until it's widened, `--provision-ids` is a documented,
   safe no-op per repo (logged, not fatal) — the fix is harmless to ship
   without that scope change, it just won't self-heal anything until the PAT
   is upgraded. **Needs a decision: widen `BADGES_PAT` to Contents:write
   fleet-wide, or accept that self-provisioning stays a logged no-op (and IDs
   get seeded some other way — e.g. a one-time local bulk run with your own
   `gh auth token`, which already has full write access) indefinitely.**
2. **Git history still has the old leak.** This PR stops the leak going
   forward, but every past commit of `manifest.json` and `badges/index.json`
   — the full name+visibility roster, going back to whenever this repo was
   first populated — is still sitting in this public repo's git history
   (and may already be cached/cloned/forked elsewhere; GitHub's own API and
   any clone taken before this merge still has it). Scrubbing that requires
   a history rewrite (`git filter-repo`/BFG) + force-push, which invalidates
   every existing clone/fork of this repo and is a materially more
   destructive, harder-to-undo action than anything else in this change.
   **Not attempted here — needs an explicit decision**: rewrite history to
   scrub the past exposure, or accept it as already-out-there and treat this
   PR as "stop the bleeding going forward only."
3. **`badges/index.json` reset to empty** rather than hand-migrated, since no
   repo has a real ID yet and inventing placeholder IDs would be actively
   misleading. It refills automatically as the scheduled poller runs (every
   6h) against repos that have (or get provisioned) an ID — flagging this
   only so the empty file isn't mistaken for a bug if someone looks right
   after merge.
