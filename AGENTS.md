# AGENTS.md

Reusable GitHub Actions workflows shared across `jluszcz` repos. See `README.md`
for the versioning model and caller examples.

**Changes here fan out to every repo in the portfolio at once.** Most callers
pin `@v2`, the current moving major tag (`@v1` is frozen — see `README.md`), so
a merge plus a release reaches ~16 repos with no action on their part. Nothing
gets a staged rollout.

## Layout

- `.github/workflows/*.yml` — the reusable workflows themselves. Anything with
  `on: workflow_call` is public API; `ci.yml` is this repo's own CI and is not.
- `scripts/release.py` — moves or cuts the version tag; `scripts/test_release.py`
  covers it.
- `README.md` — the caller-facing contract: inputs, examples, versioning.
- `CHANGELOG.md` — what changed per release. See below; it is not optional.

## Commands

```sh
uv sync --locked                              # install dependencies
uv run pytest                                 # test scripts/
uv run pre-commit run --all-files             # ruff + actionlint + hygiene
```

CI runs exactly these, plus a standalone `actionlint` job. Both `pytest` and the
hooks run offline. `pre-commit` includes `actionlint`, so a workflow edit is
checked before it is committed — do that rather than pushing to see if it parses.

## Action versions are locked in `actions.lock`

Every `uses:` of an action references a full version tag, never a commit SHA:

```yaml
uses: astral-sh/setup-uv@v10.3.3
```

`.github/workflows/actions.lock` records the commit (plus owner and repo IDs)
each tag resolved to, including transitive dependencies of composite actions,
and the runner executes that commit even if the tag later moves. A tag is
mutable and these workflows run with repository secrets in scope across every
consuming repo, so the lock — not the tag — is what makes a reference safe.
The lockfile covers the actions in reusable workflows defined here for every
caller; a caller's own lockfile does not.

After adding a workflow or changing any `uses:`, regenerate and commit the lock:

```sh
gh extension install github/gh-actions-lock --pin v0.4.1   # once
gh actions-lock                                            # rewrite actions.lock
```

Never edit `actions.lock` by hand. CI's `Actions Lockfile` job
(`actions-lock.yml`) runs `gh actions-lock --verify` and fails when the lock is
stale or a locked commit no longer verifies upstream. A full version tag that
moves upstream is an error until `gh actions-lock --relock`; review why it moved
first. Dependabot regenerates the matching lock entries in its own bump PRs.

## Concurrency groups include the call's inputs

Inside a called workflow `github.workflow` is the *caller's* workflow name, so it
does not distinguish two calls made from the same caller. Every reusable
workflow's `concurrency.group` must also include the inputs that identify the
call, or those calls share a group and cancel each other. When adding a new
input that makes one call distinct from another, add it to the group. See
`README.md` → "Concurrency".

## Changelog is updated in the PR

Every PR that changes workflow behavior MUST add an entry to `CHANGELOG.md` in
the same PR, under a `## vN — YYYY-MM-DD (short title)` heading, where `vN` is
the major it will ship under:

- Backward-compatible change (moves the current major) → heading uses that
  major (`v2` today).
- Breaking change (cuts the next major) → heading uses the next major (`v3`
  today).

The release script does NOT touch `CHANGELOG.md`; it only moves/creates the tag,
so the changelog must already be correct at release time.

**Exception:** a Dependabot PR that only bumps an action version (and its
`actions.lock` entry) or a `uv.lock` dev dependency (no other diff) does not get a `CHANGELOG.md` entry. It has no human author to write one,
and `auto-release.yml` releases it automatically on merge — see "Releasing"
below. If a PR mixes a Dependabot bump with a real behavior change, it's no
longer Dependabot-authored and the normal rule applies.

## Releasing

After the PR is merged, cut the release with the script (it tags `origin/main`'s
tip):

- Backward-compatible: `scripts/release.py -m "<what changed>"`
- Breaking: `scripts/release.py --breaking -m "<what changed>"`

The script prepends the `vN:` tag prefix to the message itself; passing a
message that already starts with `vN:` is rejected.

Preview with `--dry-run`. See `README.md` → "Releasing changes" for details.

Dependabot's own PRs (bumping an action version or a `uv.lock` dev
dependency) skip this manual step:
`self-auto-merge.yml` auto-merges them, and `auto-release.yml` then runs
`scripts/release.py -m "<PR title>" --yes` to move `v2` to the merge commit —
per `README.md`'s classification table this is always the "move current major"
case, never `--breaking`.
