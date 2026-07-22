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
`.github/workflows/**` (see `.github/workflows/ci.yml`). That same `ci.yml` also
runs a **`Python`** job that dogfoods this repo's own `python-ci.yml` (via a
local `./` ref) over `scripts/` — so the release tooling is tested with the same
`uv` + `pytest` + `pre-commit` stack consumers get. The reusable Claude
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
inputs) reuse the existing major tag. Record the change in `CHANGELOG.md` in the
same PR (see `CLAUDE.md`). After merging to `main`, cut the release:

```bash
scripts/release.py -m "<what changed>"
```

The script prefixes the message with the target tag (so the message must *not*
start with a `vN:` prefix — the script rejects it). It fetches `origin/main`,
moves `v1` to its tip, and force-pushes the tag; every consumer picks it up on
its next run. Preview with `--dry-run`. Under the hood it runs:

```bash
git tag -fa v1 <origin/main sha> -m "v1: <what changed>"   # -f re-points the tag
git push --force origin v1
```

### Breaking — cut `v2`

Changes that break existing callers (a *required* new input, a removed input, a
renamed job/status-check) get a new major tag so pinned `@v1` consumers keep
working:

```bash
scripts/release.py --breaking -m "<what changed>"
```

The script creates the next major tag (`v2`) on `origin/main`'s tip and pushes
it (no force — it's a new tag). Under the hood:

```bash
git tag -a v2 <origin/main sha> -m "v2: <what changed>"
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

### `.github/workflows/ci.yml` (Rust)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  ci:
    uses: jluszcz/github-utils/.github/workflows/rust-ci.yml@v1
    # with:                            # all optional
    #   runs-on: ubuntu-24.04-arm      # default ubuntu-latest
    #   target: aarch64-unknown-linux-musl
    #   all-features: true
```

### `.github/workflows/ci.yml` (Node)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  ci:
    uses: jluszcz/github-utils/.github/workflows/node-ci.yml@v1
    # with:
    #   node-version: '22'             # default
```

The workflow runs `npm ci` then `npm run build`, `npm test`, `npm run lint`, and
`npm run format:check`. Consumers must define all four scripts (`build`, `test`,
`lint`, `format:check`) in `package.json`, or the job fails on the missing one.

### `.github/workflows/ci.yml` (Python)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  ci:
    uses: jluszcz/github-utils/.github/workflows/python-ci.yml@v1
```

Consumers must use `uv` (with `uv.lock`) and a `.pre-commit-config.yaml`. The
job runs `uv run pytest`, so the repo must contain at least one test — pytest
exits non-zero ("no tests collected") on an empty suite and fails the job.

### `.github/workflows/ci.yml` (Rust Lambda: CI + package + deploy)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  ci:
    uses: jluszcz/github-utils/.github/workflows/rust-ci.yml@v1
    with:
      runs-on: ubuntu-24.04-arm
      target: aarch64-unknown-linux-musl
  package:
    needs: ci
    if: github.event_name == 'push'
    uses: jluszcz/github-utils/.github/workflows/lambda-package.yml@v1
    with:
      project: my-lambda
  deploy:
    needs: package
    if: github.event_name == 'push'
    permissions:                 # REQUIRED — id-token is capped by the caller
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v1
    with:
      aws-region: us-east-1
      project: my-lambda
      # regional: true           # append .${aws-region} to the role name
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}
```

`lambda-package.yml` produces `<project>.zip` (from a `lambda` binary) as artifact
`package`. `deploy-lambda.yml` assumes `${project}.github-deploy` (or
`${project}.github-deploy.${region}` when `regional: true`) and copies the zip to
`s3://code-${account}-${region}-an/`. Each `deploy-*` job **must** grant
`id-token: write` and pass the `aws-account-id` secret. Repeat the `deploy` job
per region for multi-region repos.
