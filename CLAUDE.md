# CLAUDE.md

Reusable GitHub Actions workflows shared across `jluszcz` repos. See `README.md`
for the versioning model and caller examples.

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
