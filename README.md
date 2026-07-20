# github-utils

Reusable GitHub Actions workflows shared across `jluszcz` repositories. Fix once
here; every consumer picks it up on its next run.

Consumers pin the moving major tag `@v1`. Patch/minor fixes move `v1`; breaking
changes are cut as `v2` (Dependabot opens `@v1`→`@v2` PRs).

## This repo's own protection

`main` is protected by a repository ruleset (mirroring the other `jluszcz`
repos): no branch deletion, no force-push, linear history required, and all
changes land via PR (0 required approvals, squash/rebase merges only).

The one required status check is **`Lint Workflows`** — `actionlint` over
`.github/workflows/**` (see `.github/workflows/ci.yml`). The reusable Claude
workflows are intentionally not dogfooded here: they need a
`CLAUDE_CODE_OAUTH_TOKEN` secret this repo doesn't carry, and the review action
skips whenever a PR changes a workflow file — which most PRs here do.

Inspect or edit the ruleset by fetching it (`gh api
repos/jluszcz/github-utils/rulesets/<id>`), editing the JSON, and PUTting back
only `name,target,enforcement,conditions,rules,bypass_actors`.

## Releasing changes (moving tags)

Consumers pin the moving major tag `@v1`, so a change here reaches every repo on
its next workflow run — no per-repo edits. How you release depends on whether the
change is backward-compatible.

### Patch / minor — move `v1`

Backward-compatible fixes (version bumps, condition tweaks, new *optional*
inputs) reuse the existing major tag. After merging the change to `main`:

```bash
git checkout main && git pull
git tag -fa v1 -m "v1: <what changed>"   # -f re-points the existing tag
git push --force origin v1
```

Every consumer picks it up on its next run. Record the move in `CHANGELOG.md` in
the same PR as the change.

### Breaking — cut `v2`

Changes that break existing callers (a *required* new input, a removed input, a
renamed job/status-check) get a new major tag so pinned `@v1` consumers keep
working:

```bash
git checkout main && git pull
git tag -a v2 -m "v2: <what changed>"
git push origin v2
```

Consumers then migrate `@v1` → `@v2` at their own pace. Each repo's Dependabot
`github-actions` ecosystem tracks the reusable-workflow ref and opens reviewable
bump PRs. Keep moving `v1` for backward-compatible fixes to the old major until
every consumer has migrated.

### Which is it?

| Change | Tag |
|---|---|
| Bump a pinned action version (`checkout`, `claude-code-action`) | move `v1` |
| Tweak an `if:` gate / permissions (same job names) | move `v1` |
| Add an optional `workflow_call` input with a default | move `v1` |
| Add a *required* input, or remove/rename an input | cut `v2` |
| Rename a job (changes the `<job> / <job>` status-check name) | cut `v2` |

## Callers

Each caller declares a `permissions:` block. A called reusable workflow's job
permissions cannot exceed the caller's `GITHUB_TOKEN` permissions, and these
repos default to `contents: read` only — so the caller must grant the ceiling
the reusable job needs, or the job fails to start.

### `.github/workflows/claude.yml`

```yaml
name: Claude Code
on:
  issue_comment: { types: [created] }
  pull_request_review_comment: { types: [created] }
  issues: { types: [opened, assigned] }
  pull_request_review: { types: [submitted] }
permissions:
  contents: read
  pull-requests: read
  issues: read
  id-token: write
  actions: read
jobs:
  claude:
    uses: jluszcz/github-utils/.github/workflows/claude.yml@v1
    secrets: inherit
```

### `.github/workflows/claude-code-review.yml`

```yaml
name: Claude Code Review
on:
  pull_request:
    types: [opened, synchronize, ready_for_review, reopened]
permissions:
  contents: read
  pull-requests: write
  issues: read
  id-token: write
jobs:
  claude-review:
    uses: jluszcz/github-utils/.github/workflows/claude-code-review.yml@v1
    secrets: inherit
```

### `.github/workflows/auto-merge.yml`

```yaml
name: Auto-Merge
on:
  pull_request:
    types: [opened, synchronize, reopened]
permissions:
  contents: write
  pull-requests: write
jobs:
  auto-merge:
    uses: jluszcz/github-utils/.github/workflows/auto-merge.yml@v1
    secrets: inherit
```
