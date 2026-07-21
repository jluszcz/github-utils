# Lambda Deploy Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uplift the 5 Rust/Lambda repos' packaging + deploy into reusable `lambda-package.yml` and `deploy-lambda.yml` workflows in `github-utils`, standardize the deploy IAM role to `${project}.github-deploy[.${region}]`, and migrate all 5 repos (canary first).

**Architecture:** Each Lambda repo's `ci.yml` becomes three job types — `ci` (rust-ci.yml@v1), `package` (lambda-package.yml@v1), `deploy-*` (deploy-lambda.yml@v1). The release build is isolated in `package`; deploy downloads the artifact and assumes an OIDC role. Deploy jobs run only on push-to-main.

**Tech Stack:** GitHub Actions reusable workflows, `actionlint`+`shellcheck`, `gh` CLI (rulesets), Terraform (per-repo IAM, applied by the user).

## Global Constraints

- Config/IaC, not app code: per-task "test" is `actionlint` (workflows) or `terraform validate`/plan review (TF); the true validation is a **green `ci / Build, Test & Lint` check** and a **successful post-merge deploy**. No unit tests.
- Reusable workflows live at `github-utils/.github/workflows/<name>.yml`, `on: workflow_call`.
- Action pins: `actions/checkout@v7`, `actions/upload-artifact@v7`, `actions/download-artifact@v8`, `aws-actions/configure-aws-credentials@v6.2.1`, `Swatinem/rust-cache@v2`, and `rust-ci.yml@v1`.
- Deploy IAM role: `arn:aws:iam::${account}:role/${project}.github-deploy` + (`regional` ? `.${region}` : `''`).
- Every consumer caller: job key `ci` (→ required check `ci / Build, Test & Lint`); each `deploy-*` job MUST set `permissions: { id-token: write, contents: read }` and `secrets: { aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }} }`. `ci`/`package` need no extra permissions.
- `package` + `deploy-*` are whole-job `if: github.event_name == 'push'`.
- **`terraform apply` is user-owned.** The plan writes the TF; the user applies it (per-region for regional repos) and later removes stale roles. New `-deploy` role must exist before that repo's workflow PR merges.
- Canary order: LambdUpdate → LogStreamGC → JakeSky-rs → mbtalerts → ListOfLists-rs (last; no IAM change).
- github-utils release: additive → move `v1`, recorded in `CHANGELOG.md`, same PR.
- Never `--no-verify`; never amend; feature branches only.

## File Structure

**github-utils (branch `lambda-deploy-migration`, already checked out — has the spec commits):**
- Create: `.github/workflows/lambda-package.yml`
- Create: `.github/workflows/deploy-lambda.yml`
- Modify: `README.md` (caller docs), `CHANGELOG.md`

**Consumers (each its own branch/PR):**
- Modify: `<repo>/.github/workflows/ci.yml` (all 5)
- Modify: `<repo>/<project>.tf` (add `github_deploy` role — JakeSky-rs, mbtalerts, LambdUpdate, LogStreamGC; **not** ListOfLists-rs)
- Delete: `LambdUpdate/.github/workflows/deploy-lambda.yml`, `LogStreamGC/.github/workflows/deploy-lambda.yml`
- Ruleset: rename required check → `ci / Build, Test & Lint` (all 5)

---

## Phase 1 — Reusable workflows in github-utils

On the existing `lambda-deploy-migration` branch. Both YAMLs below are already
`actionlint`-clean (with shellcheck).

### Task 1: Add `lambda-package.yml`

**Files:** Create `github-utils/.github/workflows/lambda-package.yml`

**Interfaces:**
- Produces: reusable `lambda-package.yml` — inputs `project` (required), `target` (default `aarch64-unknown-linux-musl`), `runs-on` (default `ubuntu-24.04-arm`); uploads artifact named `package` containing `<project>.zip`.

- [ ] **Step 1: Create the file** with exactly:

```yaml
name: Lambda Package

on:
  workflow_call:
    inputs:
      project:
        description: Project name; produces <project>.zip
        required: true
        type: string
      target:
        description: Rust target triple
        type: string
        default: aarch64-unknown-linux-musl
      runs-on:
        description: Runner label to execute on
        type: string
        default: ubuntu-24.04-arm

permissions:
  contents: read

jobs:
  package:
    name: Package
    runs-on: ${{ inputs.runs-on }}

    env:
      TARGET: ${{ inputs.target }}
      PROJECT: ${{ inputs.project }}

    steps:
      - uses: actions/checkout@v7

      - name: Update and Configure Rust
        run: |
          sudo apt-get install -y musl-tools
          rustup target add "$TARGET"
          rustup update

      - name: Cache Cargo
        uses: Swatinem/rust-cache@v2

      - name: Package
        run: |
          cargo build --release --target "$TARGET"
          cp "target/$TARGET/release/lambda" bootstrap
          zip -j "$PROJECT.zip" bootstrap

      - name: Upload Package
        uses: actions/upload-artifact@v7
        with:
          name: package
          path: ${{ inputs.project }}.zip
          retention-days: 1
```

- [ ] **Step 2: Validate.** Run `cd github-utils && actionlint .github/workflows/lambda-package.yml` → no output, exit 0.
- [ ] **Step 3: Commit.**
```bash
cd github-utils
git add .github/workflows/lambda-package.yml
git commit -m "feat: add reusable lambda-package workflow"
```

### Task 2: Add `deploy-lambda.yml`

**Files:** Create `github-utils/.github/workflows/deploy-lambda.yml`

**Interfaces:**
- Produces: reusable `deploy-lambda.yml` — inputs `aws-region` (required), `project` (required), `regional` (boolean, default false); secret `aws-account-id` (required); declares `permissions: id-token: write, contents: read`. Assumes `${project}.github-deploy[.${region}]`, `aws s3 cp <project>.zip s3://code-${account}-${region}-an/`.

- [ ] **Step 1: Create the file** with exactly:

```yaml
name: Deploy Lambda

on:
  workflow_call:
    inputs:
      aws-region:
        required: true
        type: string
      project:
        required: true
        type: string
      regional:
        description: Append .${aws-region} to the IAM role name
        type: boolean
        default: false

    secrets:
      aws-account-id:
        required: true

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    name: Deploy
    runs-on: ubuntu-latest

    env:
      AWS_BUCKET: code-${{ secrets.aws-account-id }}-${{ inputs.aws-region }}-an
      PROJECT: ${{ inputs.project }}

    steps:
      - name: Download Package
        uses: actions/download-artifact@v8
        with:
          name: package

      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v6.2.1
        with:
          role-to-assume: arn:aws:iam::${{ secrets.aws-account-id }}:role/${{ inputs.project }}.github-deploy${{ inputs.regional && format('.{0}', inputs.aws-region) || '' }}
          role-session-name: github-deploy
          aws-region: ${{ inputs.aws-region }}

      - name: Deploy Lambda
        run: aws s3 cp "$PROJECT.zip" "s3://$AWS_BUCKET/"
```

- [ ] **Step 2: Validate.** Run `cd github-utils && actionlint .github/workflows/deploy-lambda.yml` → no output, exit 0.
- [ ] **Step 3: Commit.**
```bash
cd github-utils
git add .github/workflows/deploy-lambda.yml
git commit -m "feat: add reusable deploy-lambda workflow"
```

### Task 3: Document callers + CHANGELOG

**Files:** Modify `github-utils/README.md`, `github-utils/CHANGELOG.md`

- [ ] **Step 1: Append to the `## Callers` section of `README.md`** (after the last existing caller subsection):

````markdown
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
````

- [ ] **Step 2: Add a `CHANGELOG.md` entry** directly under `# Changelog`:

```markdown
## v1 — 2026-07-21 (Lambda package + deploy)

Added reusable `lambda-package.yml` (release build + zip + upload) and
`deploy-lambda.yml` (OIDC assume-role + `s3 cp`). Deploy role standardized to
`${project}.github-deploy` with an optional `.${region}` suffix (`regional`
input). Additive — no change to existing callers.
```

- [ ] **Step 3: Commit.**
```bash
cd github-utils
git add README.md CHANGELOG.md
git commit -m "docs: document lambda-package and deploy-lambda callers"
```

### Task 4: Release — PR, merge, move `v1`

**Files:** none (git/release).

- [ ] **Step 1: Push + PR.**
```bash
cd github-utils
git push -u origin lambda-deploy-migration
gh pr create --fill
```
- [ ] **Step 2: Confirm CI green.** `gh pr checks --watch` → `Lint Workflows` passes (actionlint over the two new files). Merge when green (`gh pr merge --squash` if auto-merge doesn't fire).
- [ ] **Step 3: Move `v1`** using the repo's release script (per `CLAUDE.md` — do NOT hand-tag). It tags `origin/main`'s tip:
```bash
cd github-utils
git checkout main && git pull
scripts/release.py --dry-run -m "v1: add lambda-package and deploy-lambda workflows"   # preview
scripts/release.py -m "v1: add lambda-package and deploy-lambda workflows"
```
- [ ] **Step 4: Verify.** `git fetch --tags --force origin && git ls-tree --name-only v1 .github/workflows/` includes `lambda-package.yml` and `deploy-lambda.yml`.

---

## Phase 2 — Consumer migrations (canary first)

**Ordering:** requires Task 4 complete (callers pin `@v1`). Each non-ListOfLists
repo has a **user checkpoint**: apply the new `-deploy` IAM role before merging,
and remove the stale role after. Do the canary (Task 5) fully — including
watching its post-merge deploy — before starting Task 6.

### Task 5: Canary — LambdUpdate (regional, 2 regions)

**Files:** Modify `LambdUpdate/.github/workflows/ci.yml`, `LambdUpdate/lambdupdate.tf`; Delete `LambdUpdate/.github/workflows/deploy-lambda.yml`; update ruleset.

**Interfaces:**
- Consumes: `rust-ci.yml@v1`, `lambda-package.yml@v1`, `deploy-lambda.yml@v1` (regional). New role `lambdupdate.github-deploy.${region}` per region.

- [ ] **Step 1: Branch.**
```bash
cd LambdUpdate
git switch -c shared-lambda-deploy -t origin/main
```

- [ ] **Step 2: Add the duplicate `-deploy` role to `lambdupdate.tf`** (append; mirrors the existing `github` role, reusing its policy doc):

```hcl
resource "aws_iam_policy" "github_deploy" {
  name   = "lambdupdate.github-deploy.${var.aws_region}"
  policy = data.aws_iam_policy_document.github.json
}

resource "aws_iam_role" "github_deploy" {
  name = "lambdupdate.github-deploy.${var.aws_region}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.github.arn
        },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" : "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" : "repo:jluszcz/LambdUpdate:*"
          },
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.github_deploy.arn
}
```

- [ ] **Step 3: Replace `.github/workflows/ci.yml`** with exactly (preserves the current `on:`/`permissions`):

```yaml
name: CI

on:
  push:
    branches:
      - main

    paths:
      - '.github/workflows/**'
      - 'Cargo**'
      - 'src/**/*.rs'

  pull_request:
    branches:
      - main

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
      project: lambdupdate

  deploy-us-east-1:
    needs: package
    if: github.event_name == 'push'
    permissions:
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v1
    with:
      aws-region: us-east-1
      project: lambdupdate
      regional: true
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}

  deploy-us-east-2:
    needs: package
    if: github.event_name == 'push'
    permissions:
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v1
    with:
      aws-region: us-east-2
      project: lambdupdate
      regional: true
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}
```

- [ ] **Step 4: Delete the local reusable.** `cd LambdUpdate && git rm .github/workflows/deploy-lambda.yml`

- [ ] **Step 5: Validate.**
```bash
cd LambdUpdate
actionlint .github/workflows/ci.yml            # expect: clean
terraform validate 2>/dev/null || echo "terraform validate needs init/workspace — skip; user validates on apply"
```
Expected: `actionlint` clean.

- [ ] **Step 6: Commit + push + PR.**
```bash
cd LambdUpdate
git add .github/workflows/ci.yml lambdupdate.tf
git commit -m "ci: use shared rust-ci + lambda-package + deploy-lambda workflows"
git push -u origin shared-lambda-deploy
gh pr create --fill
```

- [ ] **Step 7: USER CHECKPOINT — apply the new IAM roles.** The user applies `lambdupdate.tf` from this branch in **both** region workspaces so `lambdupdate.github-deploy.us-east-1` and `...us-east-2` exist before merge:
```bash
# user runs, per the repo's Terraform docs:
. env-us_east_1 && terraform apply
. env-us_east_2 && terraform apply
```
Do not merge until the user confirms both roles exist. (Additive — the old `.github.${region}` roles and current deploy keep working meanwhile.)

- [ ] **Step 8: Update the ruleset required check** `Build, Test & Lint` → `ci / Build, Test & Lint`:
```bash
RID=$(gh api repos/jluszcz/LambdUpdate/rulesets --jq '.[0].id')
gh api "repos/jluszcz/LambdUpdate/rulesets/$RID" > /tmp/LambdUpdate-orig.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/LambdUpdate-orig.json"))
out={k:d[k] for k in ("name","target","enforcement","conditions","rules","bypass_actors")}
for r in out["rules"]:
    if r.get("type")=="required_status_checks":
        for c in r["parameters"]["required_status_checks"]:
            if c["context"]=="Build, Test & Lint": c["context"]="ci / Build, Test & Lint"
json.dump(out,open("/tmp/LambdUpdate-rs.json","w"))
PY
gh api -X PUT "repos/jluszcz/LambdUpdate/rulesets/$RID" --input /tmp/LambdUpdate-rs.json --jq '.id' >/dev/null
gh api "repos/jluszcz/LambdUpdate/rulesets/$RID" --jq '.rules[]|select(.type=="required_status_checks").parameters.required_status_checks[].context'
```
Expected: includes `ci / Build, Test & Lint`, no bare `Build, Test & Lint`.

- [ ] **Step 9: Confirm PR check + merge.** `gh pr checks --watch` (in LambdUpdate) → `ci / Build, Test & Lint` passes. Merge once green + `claude-review` resolved.

- [ ] **Step 10: VERIFY THE DEPLOY (canary gate).** Watch the post-merge push run:
```bash
gh run watch -R jluszcz/LambdUpdate "$(gh run list -R jluszcz/LambdUpdate --branch main --limit 1 --json databaseId --jq '.[0].databaseId')"
```
Confirm `package` and **both** `deploy-us-east-1` / `deploy-us-east-2` jobs succeed (OIDC assume-role works, `s3 cp` uploads). If deploy fails on role assumption, the new roles weren't applied (Step 7) or a caller `permissions`/`secrets` line is missing. **Do not proceed to Task 6 until this is green.**

- [ ] **Step 11: USER FOLLOW-UP — remove the stale role.** After confirming the deploy, the user removes the old `github` role (name `lambdupdate.github.${var.aws_region}`) from `lambdupdate.tf` and re-applies both workspaces. (Tracked as a follow-up; not blocking later tasks.)

### Task 6: LogStreamGC (regional, 2 regions)

Identical shape to Task 5 with these substitutions. **Files:** `LogStreamGC/.github/workflows/ci.yml`, `LogStreamGC/log-stream-gc.tf`, delete `LogStreamGC/.github/workflows/deploy-lambda.yml`, ruleset `10869302`.

- [ ] **Step 1: Branch.** `cd LogStreamGC && git switch -c shared-lambda-deploy -t origin/main`

- [ ] **Step 2: Append to `log-stream-gc.tf`:**
```hcl
resource "aws_iam_policy" "github_deploy" {
  name   = "log-stream-gc.github-deploy.${var.aws_region}"
  policy = data.aws_iam_policy_document.github.json
}

resource "aws_iam_role" "github_deploy" {
  name = "log-stream-gc.github-deploy.${var.aws_region}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.github.arn
        },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" : "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" : "repo:jluszcz/LogStreamGC:*"
          },
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.github_deploy.arn
}
```

- [ ] **Step 3: Replace `.github/workflows/ci.yml`** — identical to Task 5 Step 3 but `project: log-stream-gc` in the `package`, `deploy-us-east-1`, and `deploy-us-east-2` jobs (everything else identical, including both regions + `regional: true`).

- [ ] **Step 4: Delete local reusable.** `cd LogStreamGC && git rm .github/workflows/deploy-lambda.yml`
- [ ] **Step 5: Validate.** `cd LogStreamGC && actionlint .github/workflows/ci.yml` → clean.
- [ ] **Step 6: Commit + push + PR.**
```bash
cd LogStreamGC
git add .github/workflows/ci.yml log-stream-gc.tf
git commit -m "ci: use shared rust-ci + lambda-package + deploy-lambda workflows"
git push -u origin shared-lambda-deploy
gh pr create --fill
```
- [ ] **Step 7: USER CHECKPOINT** — apply `log-stream-gc.tf` in both region workspaces (`log-stream-gc.github-deploy.us-east-1` / `...us-east-2` exist) before merge.
- [ ] **Step 8: Ruleset** — same command as Task 5 Step 8 with `LogStreamGC` and ruleset id `10869302`.
- [ ] **Step 9: Merge** once `ci / Build, Test & Lint` green + claude-review resolved.
- [ ] **Step 10: Verify deploy** — watch post-merge run; both region deploys succeed.
- [ ] **Step 11: USER FOLLOW-UP** — remove stale `log-stream-gc.github.${var.aws_region}` role, re-apply.

### Task 7: JakeSky-rs (single region us-east-1, non-regional)

**Files:** `JakeSky-rs/.github/workflows/ci.yml`, `JakeSky-rs/jakesky.tf`, ruleset `18821445`. No local `deploy-lambda.yml` to delete.

- [ ] **Step 1: Branch.** `cd JakeSky-rs && git switch -c shared-lambda-deploy -t origin/main`
- [ ] **Step 2: Append to `jakesky.tf`:**
```hcl
resource "aws_iam_policy" "github_deploy" {
  name   = "jakesky.github-deploy"
  policy = data.aws_iam_policy_document.github.json
}

resource "aws_iam_role" "github_deploy" {
  name = "jakesky.github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.github.arn
        },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" : "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" : "repo:jluszcz/JakeSky-rs:*"
          },
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.github_deploy.arn
}
```

- [ ] **Step 3: Replace `.github/workflows/ci.yml`** with exactly (JakeSky's current `on:` block preserved; note JakeSky had a top-level `env: PROJECT: jakesky` — it is removed, project is now an input):

```yaml
name: CI

on:
  push:
    branches:
      - main

    paths:
      - '.github/workflows/**'
      - 'Cargo**'
      - 'src/**/*.rs'

  pull_request:
    branches:
      - main

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
      project: jakesky

  deploy:
    needs: package
    if: github.event_name == 'push'
    permissions:
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v1
    with:
      aws-region: us-east-1
      project: jakesky
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}
```

- [ ] **Step 4: Validate.** `cd JakeSky-rs && actionlint .github/workflows/ci.yml` → clean.
- [ ] **Step 5: Commit + push + PR.**
```bash
cd JakeSky-rs
git add .github/workflows/ci.yml jakesky.tf
git commit -m "ci: use shared rust-ci + lambda-package + deploy-lambda workflows"
git push -u origin shared-lambda-deploy
gh pr create --fill
```
- [ ] **Step 6: USER CHECKPOINT** — apply `jakesky.tf` (single region/workspace) so `jakesky.github-deploy` exists before merge.
- [ ] **Step 7: Ruleset** — Task 5 Step 8 command with `JakeSky-rs`, ruleset id `18821445`.
- [ ] **Step 8: Merge** once green + claude-review resolved.
- [ ] **Step 9: Verify deploy** — watch post-merge run; `deploy` (us-east-1) succeeds.
- [ ] **Step 10: USER FOLLOW-UP** — remove stale `jakesky.github` role, re-apply.

### Task 8: mbtalerts (single region us-east-2, non-regional)

**Files:** `mbtalerts/.github/workflows/ci.yml`, `mbtalerts/mbtalerts.tf`, ruleset `12950591`. Note: mbtalerts' old build job had `permissions: id-token: write` — dropped (the new `ci` job needs none).

- [ ] **Step 1: Branch.** `cd mbtalerts && git switch -c shared-lambda-deploy -t origin/main`
- [ ] **Step 2: Append to `mbtalerts.tf`:**
```hcl
resource "aws_iam_policy" "github_deploy" {
  name   = "mbtalerts.github-deploy"
  policy = data.aws_iam_policy_document.github.json
}

resource "aws_iam_role" "github_deploy" {
  name = "mbtalerts.github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.github.arn
        },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" : "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" : "repo:jluszcz/mbtalerts:*"
          },
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.github_deploy.arn
}
```

- [ ] **Step 3: Replace `.github/workflows/ci.yml`** — identical to Task 7 Step 3 but `project: mbtalerts` (in `package` + `deploy`) and `aws-region: us-east-2` (in `deploy`). mbtalerts' current `on:` block matches (paths `.github/workflows/**`, `Cargo**`, `src/**/*.rs`); the top-level `env: PROJECT` and the build-job `id-token` are removed.
- [ ] **Step 4: Validate.** `cd mbtalerts && actionlint .github/workflows/ci.yml` → clean.
- [ ] **Step 5: Commit + push + PR.**
```bash
cd mbtalerts
git add .github/workflows/ci.yml mbtalerts.tf
git commit -m "ci: use shared rust-ci + lambda-package + deploy-lambda workflows"
git push -u origin shared-lambda-deploy
gh pr create --fill
```
- [ ] **Step 6: USER CHECKPOINT** — apply `mbtalerts.tf` so `mbtalerts.github-deploy` exists before merge.
- [ ] **Step 7: Ruleset** — Task 5 Step 8 command with `mbtalerts`, ruleset id `12950591`.
- [ ] **Step 8: Merge** once green + claude-review resolved.
- [ ] **Step 9: Verify deploy** — watch post-merge run; `deploy` (us-east-2) succeeds.
- [ ] **Step 10: USER FOLLOW-UP** — remove stale `mbtalerts.github` role, re-apply.

### Task 9: ListOfLists-rs (single region us-east-2, NO IAM change)

**Files:** `ListOfLists-rs/.github/workflows/ci.yml`, ruleset `10869287`. **No TF change** — `list-of-lists.github-deploy` already exists (`regional: false`). Confirm the current `secrets.AWS_DEFAULT_REGION` is `us-east-2` before hardcoding.

- [ ] **Step 1: Branch.** `cd ListOfLists-rs && git switch -c shared-lambda-deploy -t origin/main`
- [ ] **Step 2: Replace `.github/workflows/ci.yml`** with exactly (ListOfLists' current `on:` uses `paths: ['.github/workflows/ci.yml', ...]` — preserved; top-level `env: PROJECT: list-of-lists` removed):

```yaml
name: CI

on:
  push:
    branches:
      - main

    paths:
      - '.github/workflows/ci.yml'
      - 'Cargo**'
      - 'src/**/*.rs'

  pull_request:
    branches:
      - main

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
      project: list-of-lists

  deploy:
    needs: package
    if: github.event_name == 'push'
    permissions:
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v1
    with:
      aws-region: us-east-2
      project: list-of-lists
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}
```

- [ ] **Step 3: Validate.** `cd ListOfLists-rs && actionlint .github/workflows/ci.yml` → clean.
- [ ] **Step 4: Commit + push + PR.**
```bash
cd ListOfLists-rs
git add .github/workflows/ci.yml
git commit -m "ci: use shared rust-ci + lambda-package + deploy-lambda workflows"
git push -u origin shared-lambda-deploy
gh pr create --fill
```
- [ ] **Step 5: Ruleset** — Task 5 Step 8 command with `ListOfLists-rs`, ruleset id `10869287`.
- [ ] **Step 6: Merge** once `ci / Build, Test & Lint` green + claude-review resolved. (No IAM checkpoint — the `list-of-lists.github-deploy` role already exists.)
- [ ] **Step 7: Verify deploy** — watch post-merge run; `deploy` (us-east-2) succeeds. If the previous region was **not** us-east-2, revisit Step 2's hardcode.

---

## Post-completion

- Follow-up (repo precedent): remove the spec + this plan from `github-utils/docs/superpowers/` via a PR once all 5 repos are migrated.
- The stale-role cleanups (Task 5/6/7/8 Step 11/10) are user-owned and tracked separately; ListOfLists has none.
- Update the `[[shared-workflows-migration]]` memory: all 5 Lambda repos migrated; deployment no longer deferred.
