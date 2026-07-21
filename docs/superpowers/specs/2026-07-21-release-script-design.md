# Release script design

**Date:** 2026-07-21
**Status:** Approved

## Problem

Releasing this repo means moving the consumer-pinned major tag (`v1`) to the tip
of `origin/main`, or cutting the next major (`v2`) for a breaking change. Today
this is a manual `git tag -fa` / `git push --force` sequence documented in the
README. We want a single command that does it correctly and safely.

## Scope

A Python script, `scripts/release.py`, that manages **only the version tag**. It
never edits `CHANGELOG.md`. The changelog is updated inside each feature PR; a
new repo-level `CLAUDE.md` rule enforces that so the changelog is always current
by the time a release is cut.

## CLI

```
scripts/release.py -m "v1: bump checkout to v5"
scripts/release.py --breaking -m "v2: require 'target' input"
scripts/release.py -m "..." --dry-run
```

Flags:

| Flag | Meaning |
|---|---|
| `-m`, `--message` | **Required.** Annotated-tag message. |
| `--breaking` | Create the next major tag instead of moving the current one. |
| `--dry-run` | Print the git commands; execute nothing, push nothing. |
| `--yes` | Skip the confirmation prompt (default: prompt before pushing). |
| `--remote` | Default `origin`. |
| `--branch` | Default `main`. |

`--major N` (moving an older major after a newer one is cut) is intentionally
out of scope — it's a rare case left to a manual `git tag`.

## Behavior

1. `git fetch <remote> <branch>` so the tag lands on the true remote tip.
2. Read existing tags (`git tag -l 'v*'`) and compute the current highest major
   `vN`.
3. Resolve the target:
   - **default (move):** tag `vN` — `git tag -fa vN <sha> -m <msg>` then
     `git push --force <remote> vN`.
   - **`--breaking` (create):** tag `v(N+1)` — `git tag -a v(N+1) <sha> -m <msg>`
     then `git push <remote> v(N+1)`.
   - Both point at the resolved `origin/<branch>` SHA.
4. Print a summary (tag name, move-vs-create, old→new SHA, force-push warning),
   prompt for confirmation (unless `--yes`), then run the commands.

## Structure (testability)

Pure functions separated from side effects so the logic is unit-testable without
invoking git:

- `current_major(tags: list[str]) -> int` — highest `vN` among tags; `0` if none.
- `resolve_target(current: int, breaking: bool) -> tuple[str, bool]` — returns
  `(tag_name, is_move)`.
- `build_commands(tag, sha, message, is_move, remote) -> list[list[str]]` — the
  git command sequence.
- `main()` — thin orchestration: parse args, shell out for tags/fetch/SHA,
  confirm, run.

## Testing

Stdlib `unittest` in `scripts/test_release.py` (no new dependencies, run via
`python -m unittest`). Cases:

- `current_major`: parses `['v1']` → 1, mixed/non-version tags ignored, empty → 0.
- `resolve_target`: default of `v1` → `('v1', True)`; `--breaking` of `v1` →
  `('v2', False)`; `--breaking` with no tags → `('v1', False)`.
- `build_commands`: move uses `-f`/`--force`; create omits both; SHA and message
  are threaded through.

## Edge cases

- No existing tags + default (move): error — "no version tag to move; use
  --breaking to cut the first release".
- No existing tags + `--breaking`: creates `v1`.
- `origin/<branch>` cannot be resolved after fetch: error out before tagging.
- `--dry-run` performs the fetch (read-only) but neither tags nor pushes.

## Docs

- **New `CLAUDE.md`:** every behavior-changing PR must add a `## vN — <date>`
  entry to `CHANGELOG.md`; releases are cut with `scripts/release.py`.
- **`README.md`:** update the "Releasing changes" section to lead with the
  script, keeping the manual git commands as the underlying reference.
