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

Inspect or edit the ruleset with the procedure in
`docs/superpowers/plans/2026-07-20-shared-workflows.md` (fetch via
`gh api repos/jluszcz/github-utils/rulesets/<id>`; PUT back `name,target,
enforcement,conditions,rules,bypass_actors`).

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
