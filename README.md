# github-utils

Reusable GitHub Actions workflows shared across `jluszcz` repositories. Fix once
here; every consumer picks it up on its next run.

Consumers pin the current major tag `@v2`; `@v1` is frozen (see "Releasing
changes" below). Patch/minor fixes move the current major tag; breaking changes
cut the next one. Dependabot opens `@v1`→`@v2` bump PRs for consumers still on
the frozen tag.

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

Consumers pin the current major tag (`@v2` today), so a change here reaches
every repo pinned to it on its next workflow run — no per-repo edits. `@v1` is
frozen; see "`v1` is frozen" below. How you release depends on whether the
change is backward-compatible.

### Patch / minor — move the current major

Backward-compatible fixes (version bumps, condition tweaks, new *optional*
inputs) reuse the current major tag. Record the change in `CHANGELOG.md` in the
same PR (see `CLAUDE.md`). After merging to `main`, cut the release:

```bash
scripts/release.py -m "<what changed>"
```

The script prefixes the message with the target tag (so the message must *not*
start with a `vN:` prefix — the script rejects it). It fetches `origin/main`,
resolves the current major as the highest existing `v*` tag (`v2` today), moves
that tag to the tip, and force-pushes it; every consumer pinned to it picks up
the change on its next run. Preview with `--dry-run`. Under the hood, for `v2`:

```bash
git tag -fa v2 <origin/main sha> -m "v2: <what changed>"   # -f re-points the tag
git push --force origin v2
```

### Breaking — cut the next major

Changes that break existing callers (a *required* new input, a removed input, a
renamed job/status-check) get a new major tag so pinned `@v2` consumers keep
working:

```bash
scripts/release.py --breaking -m "<what changed>"
```

The script creates the next major tag on `origin/main`'s tip and pushes it (no
force — it's a new tag). Under the hood, for the major after `v2`:

```bash
git tag -a v3 <origin/main sha> -m "v3: <what changed>"
git push origin v3
```

Consumers then migrate `@v2` → `@v3` at their own pace. Each repo's Dependabot
`github-actions` ecosystem tracks the reusable-workflow ref and opens reviewable
bump PRs.

### Dependabot bumps release themselves

Dependabot's own PRs here (bumping a pinned third-party action SHA) don't wait
for a manual release. `self-auto-merge.yml` auto-merges them once required
checks pass, and `auto-release.yml` then runs `scripts/release.py -m "<PR
title>" --yes` to move `v2` to the merge commit. These bumps are always the
"move current major" case in the table below, never breaking, and they're the
one exception to `CLAUDE.md`'s "changelog updated in the same PR" rule — a
Dependabot PR has no human author to write that entry.

The chain only runs when `auto-merge.yml` has App credentials. A merge made with
the default `GITHUB_TOKEN` creates no `pull_request: closed` event, so
`auto-release.yml` never starts and `v2` has to be moved by hand — see
`auto-merge.yml` under "Callers" below.

### `v1` is frozen

`scripts/release.py`'s `current_major()` takes the `max()` of the existing `v*`
tags, and a non-breaking release always moves *that* tag — there is no
`--tag`/`--major` flag to target an older major. Once `v2` was cut, `v1` stopped
being reachable by `scripts/release.py -m ...`: it is frozen at its last commit
and there is no tooling path back to it. Consumers still pinned to `@v1` do not
get backported fixes; they catch up only by taking the Dependabot `@v1` → `@v2`
bump, which is a no-op for every workflow `v2` didn't change (only
`deploy-lambda.yml` did — see its `CHANGELOG.md` entry).

### Which is it?

| Change | Tag |
|---|---|
| Bump a pinned action version (`checkout`, `claude-code-action`) | move current major |
| Tweak an `if:` gate / permissions (same job names) | move current major |
| Add an optional `workflow_call` input with a default | move current major |
| Add a *required* input, or remove/rename an input | cut next major |
| Rename a job (changes the `<job> / <job>` status-check name) | cut next major |

## Callers

Each caller declares a `permissions:` block. A called reusable workflow's job
permissions cannot exceed the caller's `GITHUB_TOKEN` permissions, and these
repos default to `contents: read` only — so the caller must grant the ceiling
the reusable job needs, or the job fails to start.

### Concurrency

Each reusable workflow sets its own `concurrency` group so a superseded run is
cancelled and the latest wins. The group includes the **inputs that identify the
call**, not just the workflow name — inside a called workflow `github.workflow`
resolves to the *caller's* workflow name, so every call from one caller shares
it. Without the inputs, calling the same reusable workflow twice in one caller
(e.g. a `deploy` job per region) puts both in one group with
`cancel-in-progress: true`, and they cancel each other.

Callers need no `concurrency` block of their own. When adding an input that
distinguishes one call from another, add it to that workflow's group too.

### `.github/workflows/claude.yml`

```yaml
name: Claude Code
on:
  issue_comment: { types: [created] }
  pull_request_review_comment: { types: [created] }
  issues: { types: [opened, assigned] }
  pull_request_review: { types: [submitted] }
permissions:
  contents: write
  pull-requests: read
  issues: read
  id-token: write
  actions: read
jobs:
  claude:
    uses: jluszcz/github-utils/.github/workflows/claude.yml@v2
    secrets: inherit
```

`contents: write` is what lets Claude push a commit to the PR branch when a
comment asks it to fix something. Drop it to `read` in a repo where Claude
should only ever comment; the reusable job's own `contents: write` is a ceiling,
not a floor, so the caller's value wins when it is lower.

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
    uses: jluszcz/github-utils/.github/workflows/claude-code-review.yml@v2
    secrets: inherit
    # with:
    #   debug: true                    # default false
```

Reviews run when the PR is opened, reopened, or marked ready for review — not on
every subsequent push. Keep `synchronize` in the trigger types anyway: the job
still runs and reports success on each new head commit, which a required status
check needs, it just doesn't post another review. To request one on a later push,
comment `@claude review this PR` on the PR (handled by `claude.yml`).

A PR that edits this workflow file does not get reviewed. `claude-code-action`
validates that its own workflow file on the PR head is byte-identical to the
copy on the default branch, and skips itself when it is not — a PR cannot amend
the workflow that reviews it. The step still reports success, so the check is
green and the only trace is a `Skipping action due to workflow validation`
warning in the job log. Merging is what makes such a change take effect, and a
branch that predates the merge needs the default branch merged into it before
its next review picks the change up.

`debug: true` keeps Claude's execution log — the full turn stream, including a
`permission_denials` entry per blocked call naming the tool and its input — as a
`claude-execution-log` artifact on the run. Reach for it when a review finishes
green without posting a review: the action hides that stream by default, and
rerunning the job with Actions debug logging does not bring it back, so the run
otherwise says nothing about where Claude stopped. Download it with
`gh run download <run-id> -n claude-execution-log`. Leave it off the rest of the
time — the log is the review verbatim, diff and file contents included, and it
is readable by anyone who can read the repo's Actions runs.

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
    uses: jluszcz/github-utils/.github/workflows/auto-merge.yml@v2
    secrets: inherit
```

`auto-merge.yml` merges with a GitHub App installation token when `APP_ID` and
`APP_PRIVATE_KEY` are present as repository secrets, and falls back to the
default `GITHUB_TOKEN` when they are not. Both are optional `workflow_call`
secrets declared under their uppercase repository-secret names, so the
`secrets: inherit` above passes them through with no further caller YAML.

The fallback is not equivalent. GitHub creates no workflow runs for events
triggered by `GITHUB_TOKEN`, so a merge made with it fires neither `push` nor
`pull_request: closed`: a repo that gates deploys on `push` to `main` lands the
bump and never ships it, and `auto-release.yml` here never moves `v2`. A repo
without the secrets has that behavior; adding them restores the events.

The App must be installed on the calling repo, with these repository
permissions:

| Permission | Level | Why |
| --- | --- | --- |
| Contents | Read and write | The squash merge writes to the branch |
| Pull requests | Read and write | Enabling auto-merge |
| Metadata | Read | Mandatory baseline |

`create-github-app-token` mints a token scoped to that one installation, which
expires in an hour. `jluszcz` is a User account, so there are no organization
secrets — provision per repo, and re-run the same loop to rotate the key:

```sh
gh secret set APP_ID --repo "jluszcz/$REPO" --body "$APP_ID"
gh secret set APP_PRIVATE_KEY --repo "jluszcz/$REPO" < private-key.pem
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
    uses: jluszcz/github-utils/.github/workflows/rust-ci.yml@v2
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
    uses: jluszcz/github-utils/.github/workflows/node-ci.yml@v2
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
    uses: jluszcz/github-utils/.github/workflows/python-ci.yml@v2
```

Consumers must use `uv` (with `uv.lock`) and a `.pre-commit-config.yaml`. The
job runs `uv run pytest`, so the repo must contain at least one test — pytest
exits non-zero ("no tests collected") on an empty suite and fails the job.

### `.github/workflows/ci.yml` (Terraform)

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
  terraform:
    uses: jluszcz/github-utils/.github/workflows/terraform-ci.yml@v2
    # with:
    #   directories: |                 # default '.'
    #     shared
    #     sites/example.com
```

`terraform fmt -check -recursive -diff` runs once from the repo root, so it
covers every `.tf` file regardless of `directories`. `terraform init
-backend=false` then `terraform validate` run once per entry in `directories` —
`-backend=false` keeps the job offline, so it needs no S3 backend and no AWS
credentials, and each root's provider versions come from its committed
`.terraform.lock.hcl`.

Set `directories` in a repo whose Terraform lives anywhere other than the root,
listing every root that has its own `.terraform.lock.hcl` plus any shared module
directory. A root left off the list is still format-checked but never validated.

This job is usually one job among several — add it alongside the `rust-ci.yml`
call in a Rust repo that also carries its own infrastructure.

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
    uses: jluszcz/github-utils/.github/workflows/rust-ci.yml@v2
    with:
      runs-on: ubuntu-24.04-arm
      target: aarch64-unknown-linux-musl
  package:
    needs: ci
    if: github.event_name == 'push'
    uses: jluszcz/github-utils/.github/workflows/lambda-package.yml@v2
    with:
      project: my-lambda
  deploy:
    needs: package
    if: github.event_name == 'push'
    permissions:                 # REQUIRED — id-token is capped by the caller
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v2
    with:
      aws-region: us-east-1
      project: my-lambda
      # regional: true           # append .${aws-region} to the role name
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}
```

`lambda-package.yml` produces `<project>.zip` (from a `lambda` binary) as artifact
`package`. `deploy-lambda.yml` assumes `${project}.github-deploy` (or
`${project}.github-deploy.${region}` when `regional: true`), copies the zip to
`s3://code-${account}-${region}-an/`, then calls `UpdateFunctionCode` on the
function named by `project` and waits for the update to complete successfully.
The role therefore needs four permissions: `s3:PutObject` on the object;
`s3:GetObject` on the same object, because `update-function-code` with an S3
source has Lambda fetch the object using the *caller's* credentials, not the
function's execution role; and `lambda:UpdateFunctionCode` plus
`lambda:GetFunction` (which backs the waiter) on the function. Each `deploy-*`
job **must** grant `id-token: write` and pass the `aws-account-id` secret.
Repeat the `deploy` job per region for multi-region repos — each region gets its
own concurrency group (see "Concurrency"), so the regions do not cancel each
other.

For a brand-new project whose Lambda doesn't exist yet, this step fails with
`ResourceNotFoundException` on the first deploy — the function must exist
before its code can be updated. Run `terraform apply` to create it, then
re-run the deploy job.

`lambda-package.yml` always uploads its artifact as `package`, so a caller can
only run one packaging job per run; a repo with two lambdas needs a change here
first.

### `.github/workflows/workflow.yml` (minify JSON + upload to S3)

```yaml
name: Upload to S3
on:
  push:
    branches: [main]
    paths:
      - burgerlist.json
      - .github/workflows/workflow.yml
permissions:
  contents: read
jobs:
  minify-and-upload-to-s3:
    permissions:                 # REQUIRED — id-token is capped by the caller
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/minify-and-upload.yml@v2
    with:
      aws-region: us-east-2
      project: burgerlist        # -> burgerlist.json, role burgerlist.github-update
      s3-key-prefix: burgerl.ist # -> burgerl.ist.json
      bucket-prefix: list-of-lists
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}
```

`minify-and-upload.yml` runs `jq --compact-output '.lists |= map(select(.hidden
!= true))'` over `${project}.json`, assumes `${project}.github-update`, and
copies the result to
`s3://${bucket-prefix}-${account}-${region}-an/${s3-key-prefix}.json`. The `jq`
filter and the `.github-update` role suffix are fixed — a consumer that needs
different ones needs a new input here first.

`aws-region` is an input rather than a secret because a reusable workflow's
`with:` block cannot reference the `secrets` context (only `github`, `needs`,
`inputs`, `vars`, `matrix`, and `strategy`). Pass the region literally, or from
a repo/org `vars` entry.
