# CLAUDE.md

Reusable GitHub Actions workflows shared across `jluszcz` repos. See `README.md`
for the versioning model and caller examples.

**Changes here fan out to every repo in the portfolio at once.** Callers pin to
`@v1`, which is a moving tag, so a merge plus a release reaches ~16 repos with no
action on their part. Nothing gets a staged rollout.

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

## Pin third-party actions to a commit SHA

Any `uses:` outside the `actions/*` namespace must be a full commit SHA with the
human-readable version in a trailing comment:

```yaml
uses: astral-sh/setup-uv@d31148d669074a8d0a63714ba94f3201e7020bc3 # v8.3.0
```

A tag is mutable, and these workflows run with repository secrets in scope
across every consuming repo. First-party `actions/*` stay on major tags
(`actions/checkout@v7`) — GitHub controls that namespace.

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

- Backward-compatible change (moves `v1`) → heading `## v1 — <date> (...)`.
- Breaking change (cuts the next major) → heading `## v2 — <date> (...)`.

The release script does NOT touch `CHANGELOG.md`; it only moves/creates the tag,
so the changelog must already be correct at release time.

## Releasing

After the PR is merged, cut the release with the script (it tags `origin/main`'s
tip):

- Backward-compatible: `scripts/release.py -m "<what changed>"`
- Breaking: `scripts/release.py --breaking -m "<what changed>"`

The script prepends the `vN:` tag prefix to the message itself; passing a
message that already starts with `vN:` is rejected.

Preview with `--dry-run`. See `README.md` → "Releasing changes" for details.
