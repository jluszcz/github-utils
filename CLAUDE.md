# CLAUDE.md

Reusable GitHub Actions workflows shared across `jluszcz` repos. See `README.md`
for the versioning model and caller examples.

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

- Backward-compatible: `scripts/release.py -m "v1: <what changed>"`
- Breaking: `scripts/release.py --breaking -m "v2: <what changed>"`

Preview with `--dry-run`. See `README.md` → "Releasing changes" for details.
