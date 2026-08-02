# Retire LambdUpdate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `deploy-lambda.yml` call `UpdateFunctionCode` itself, then destroy and archive LambdUpdate.

**Architecture:** The workflow keeps its `aws s3 cp` (Terraform still needs an object in S3 to create a function) and gains a retry-on-conflict `update-function-code` step plus a `wait function-updated-v2`. Each caller's `github-deploy` role gains `lambda:UpdateFunctionCode` and `lambda:GetFunction` scoped to its own function, replacing LambdUpdate's account-wide `function:*` grant. The change is cut as `v2` so each repo migrates its own pin; the S3 bucket notification comes down only after all four migrate.

**Tech Stack:** GitHub Actions reusable workflows, AWS CLI v2, Terraform (S3 backend `jluszcz-tf-state`), `actionlint`/`shellcheck` via pre-commit.

**Source spec:** `docs/superpowers/specs/2026-08-02-lambdupdate-retirement-design.md`

## Global Constraints

- **Repos are separate checkouts** under `/Users/jacob/Documents/Programs/`. Every task names the repo it runs in. Never commit onto a default branch — branch first (`jluszcz:commit` skill handles this).
- **Never `--no-verify`, never amend.** If a hook edits files, restage and commit fresh.
- **Third-party actions pin to a full commit SHA** with the version in a trailing comment. `actions/*` stay on major tags. (`github-utils/CLAUDE.md`)
- **A concurrency group must include any new input that distinguishes one call.** This plan adds no inputs, so `deploy-lambda.yml`'s group is unchanged. (`github-utils/CLAUDE.md`)
- **Every github-utils PR that changes workflow behavior adds a `CHANGELOG.md` entry** in the same PR, heading `## vN — YYYY-MM-DD (short title)`. (`github-utils/CLAUDE.md`)
- **Retry only on `ResourceConflictException`.** Any other failure exits on the first attempt with its real error.
- **Each deploy role needs four permissions, not three: `s3:PutObject`, `s3:GetObject`, `lambda:UpdateFunctionCode`, `lambda:GetFunction`.** `update-function-code` with an S3 source has Lambda fetch the artifact using the *caller's* credentials, not the function's execution role, so `s3:GetObject` on the artifact belongs on the same statement as `s3:PutObject` in Tasks 1–4. This was missed in an earlier version of this plan and surfaced by a real deploy's `AccessDeniedException`.
- **Function name == `inputs.project`** for all callers. No `function-name` input is added.
- **Steps marked [you] need real credentials or GitHub admin** — Terraform applies read secrets from your environment (`mbtalerts` and `JakeSky-rs` require `TF_VAR_*` values not in the repo), `release.py` pushes tags, and archiving needs repo admin. An agent executing this plan must stop and hand those to you rather than guess.

## File Structure

| Repo | File | Change |
|---|---|---|
| github-utils | `.github/workflows/deploy-lambda.yml` | Add the update step; rename the upload step |
| github-utils | `README.md` | `deploy-lambda.yml` paragraph + that example block's pins |
| github-utils | `CHANGELOG.md` | `## v2` entry |
| LogStreamGC | `log-stream-gc.tf` | IAM statement |
| LogStreamGC | `.github/workflows/ci.yml` | Two pins `@v1` → `@v2` |
| ListOfLists-rs | `shared/main.tf` | IAM statement |
| ListOfLists-rs | `.github/workflows/ci.yml` | One pin |
| mbtalerts | `mbtalerts.tf` | IAM statement |
| mbtalerts | `.github/workflows/ci.yml` | One pin |
| mbtalerts | `CLAUDE.md:95-98` | Deployment paragraph |
| JakeSky-rs | `jakesky.tf` | IAM statement |
| JakeSky-rs | `.github/workflows/ci.yml` | One pin |
| LambdUpdate | `lambdupdate.tf` | Delete notification + permission, then destroy |
| LambdUpdate | `README.md` | Retirement note |

Tasks 1–4 are independent of each other and can run in any order. Task 5 depends on all four being **applied**, not just merged. Tasks 6–9 each depend on Task 5. Task 10 depends on all of 6–9. Task 11 depends on 10.

---

### Task 1: Grant LogStreamGC's deploy role Lambda permissions

**Repo:** `/Users/jacob/Documents/Programs/LogStreamGC`

**Files:**
- Modify: `log-stream-gc.tf:105-110`

**Interfaces:**
- Consumes: nothing.
- Produces: the `log-stream-gc.github-deploy.<region>` role can call `UpdateFunctionCode` and `GetFunction` on `arn:aws:lambda:<region>:<account>:function:log-stream-gc`, and `GetObject` on its own artifact in the code bucket. Task 6 depends on this being applied in **both** regions.

- [ ] **Step 1: Add the statement**

In `log-stream-gc.tf`, the policy document currently reads:

```hcl
data "aws_iam_policy_document" "github" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${data.aws_s3_bucket.code_bucket.arn}/log-stream-gc.zip"]
  }
}
```

Make it:

```hcl
data "aws_iam_policy_document" "github" {
  # GetObject: update-function-code with an S3 source has Lambda fetch the
  # object using these credentials, not the function's execution role.
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${data.aws_s3_bucket.code_bucket.arn}/log-stream-gc.zip"]
  }

  # GetFunction backs the `aws lambda wait function-updated-v2` in deploy-lambda.yml.
  statement {
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
    resources = [aws_lambda_function.log_stream_gc.arn]
  }
}
```

- [ ] **Step 2: Verify the plan in us-east-1 [you]**

```bash
cd /Users/jacob/Documents/Programs/LogStreamGC
. env-us_east_1
terraform plan
```

Expected: exactly one change — `aws_iam_policy.github_deploy` updated in place, its `policy` JSON gaining `s3:GetObject` on the existing `s3:PutObject` statement and a new statement with `lambda:UpdateFunctionCode` and `lambda:GetFunction`. **No** other resource added, changed, or destroyed. If the plan wants to touch `aws_lambda_function` or anything else, stop — the working tree has drifted.

- [ ] **Step 3: Apply both regions [you]**

```bash
. env-us_east_1 && terraform apply
. env-us_east_2 && terraform apply
```

- [ ] **Step 4: Confirm the grant landed**

```bash
aws iam get-policy-version \
  --policy-arn "arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/log-stream-gc.github-deploy.us-east-1" \
  --version-id "$(aws iam get-policy --policy-arn "arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/log-stream-gc.github-deploy.us-east-1" --query 'Policy.DefaultVersionId' --output text)" \
  --query 'PolicyVersion.Document'
```

Expected: the decoded document lists `s3:GetObject` alongside `s3:PutObject`, and `lambda:UpdateFunctionCode` and `lambda:GetFunction`. Repeat with `.us-east-2` for the second region.

- [ ] **Step 5: Commit**

Use the `jluszcz:commit` skill. Message:

```
feat(iam): let the deploy role update the function directly

deploy-lambda.yml is moving from "upload and let LambdUpdate notice" to
calling UpdateFunctionCode itself. GetFunction backs the waiter that
confirms the new code went active.
```

Nothing uses the grant until this repo's pin moves to `@v2` in Task 6, so this is safe to apply and leave.

---

### Task 2: Grant ListOfLists-rs's deploy role Lambda permissions

**Repo:** `/Users/jacob/Documents/Programs/ListOfLists-rs`

**Files:**
- Modify: `shared/main.tf:258-263`

**Interfaces:**
- Consumes: nothing.
- Produces: `list-of-lists.github-deploy` can call `UpdateFunctionCode`/`GetFunction` on the `list-of-lists` function, and `GetObject` on its own artifact in the code bucket. Task 9 depends on it.

Note: this repo's document is named `github_deploy` (not `github` like the others), the function resource is `aws_lambda_function.lambda`, and Terraform runs from inside `shared/` with a `.envrc` — there are no workspaces and no `env-*` scripts.

- [ ] **Step 1: Add the statement**

In `shared/main.tf`, under the `# GitHub Actions: deploy Lambda code` comment:

```hcl
data "aws_iam_policy_document" "github_deploy" {
  # GetObject: update-function-code with an S3 source has Lambda fetch the
  # object using these credentials, not the function's execution role.
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${data.aws_s3_bucket.code_bucket.arn}/list-of-lists.zip"]
  }

  # GetFunction backs the `aws lambda wait function-updated-v2` in deploy-lambda.yml.
  statement {
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
    resources = [aws_lambda_function.lambda.arn]
  }
}
```

- [ ] **Step 2: Verify the plan [you]**

```bash
cd /Users/jacob/Documents/Programs/ListOfLists-rs/shared
terraform plan
```

Expected: one in-place update to `aws_iam_policy.github_deploy`, nothing else. In particular `aws_lambda_function.lambda` must show no diff — it carries `lifecycle { ignore_changes = [s3_bucket, s3_key, s3_object_version] }` precisely so out-of-band code deploys don't show up here.

- [ ] **Step 3: Apply [you]**

```bash
terraform apply
```

- [ ] **Step 4: Commit**

Use the `jluszcz:commit` skill. Message:

```
feat(iam): let the deploy role update the function directly

deploy-lambda.yml is moving from "upload and let LambdUpdate notice" to
calling UpdateFunctionCode itself. GetFunction backs the waiter that
confirms the new code went active.
```

---

### Task 3: Grant mbtalerts's deploy role Lambda permissions

**Repo:** `/Users/jacob/Documents/Programs/mbtalerts`

**Files:**
- Modify: `mbtalerts.tf:126-131`

**Interfaces:**
- Consumes: nothing.
- Produces: `mbtalerts.github-deploy` can call `UpdateFunctionCode`/`GetFunction` on the `mbtalerts` function, and `GetObject` on its own artifact in the code bucket. Task 8 depends on it.

- [ ] **Step 1: Add the statement**

```hcl
data "aws_iam_policy_document" "github" {
  # GetObject: update-function-code with an S3 source has Lambda fetch the
  # object using these credentials, not the function's execution role.
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${data.aws_s3_bucket.code_bucket.arn}/mbtalerts.zip"]
  }

  # GetFunction backs the `aws lambda wait function-updated-v2` in deploy-lambda.yml.
  statement {
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
    resources = [aws_lambda_function.mbtalerts.arn]
  }
}
```

- [ ] **Step 2: Verify the plan [you]**

This root module takes `TF_VAR_service_acct_key`, `TF_VAR_aws_region`, and the calendar variables from your environment — there is no `env-*` script in the repo. Set them the way you normally do, then:

```bash
cd /Users/jacob/Documents/Programs/mbtalerts
terraform plan
```

Expected: one in-place update to `aws_iam_policy.github_deploy`, nothing else. If the plan also wants to change the Bedrock policy or the EventBridge schedule, stop — that is unrelated drift and should be resolved before this change lands.

- [ ] **Step 3: Apply [you]**

```bash
terraform apply
```

- [ ] **Step 4: Commit**

Use the `jluszcz:commit` skill. Message:

```
feat(iam): let the deploy role update the function directly

deploy-lambda.yml is moving from "upload and let LambdUpdate notice" to
calling UpdateFunctionCode itself. GetFunction backs the waiter that
confirms the new code went active.
```

---

### Task 4: Grant JakeSky-rs's deploy role Lambda permissions

**Repo:** `/Users/jacob/Documents/Programs/JakeSky-rs`

**Files:**
- Modify: `jakesky.tf:116-121`

**Interfaces:**
- Consumes: nothing.
- Produces: `jakesky.github-deploy` can call `UpdateFunctionCode`/`GetFunction` on the `jakesky` function, and `GetObject` on its own artifact in the code bucket. Task 7 depends on it.

- [ ] **Step 1: Add the statement**

```hcl
data "aws_iam_policy_document" "github" {
  # GetObject: update-function-code with an S3 source has Lambda fetch the
  # object using these credentials, not the function's execution role.
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${data.aws_s3_bucket.code_bucket.arn}/jakesky.zip"]
  }

  # GetFunction backs the `aws lambda wait function-updated-v2` in deploy-lambda.yml.
  statement {
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
    resources = [aws_lambda_function.jakesky.arn]
  }
}
```

- [ ] **Step 2: Verify the plan [you]**

`jakesky.tf` reads `TF_VAR_jakesky_api_key`, `TF_VAR_jakesky_skill_id`, `TF_VAR_jakesky_latitude`, and `TF_VAR_jakesky_longitude` from your environment; `aws_region` defaults to `us-east-1`.

```bash
cd /Users/jacob/Documents/Programs/JakeSky-rs
terraform plan
```

Expected: one in-place update to `aws_iam_policy.github_deploy`, nothing else.

- [ ] **Step 3: Apply [you]**

```bash
terraform apply
```

- [ ] **Step 4: Commit**

Use the `jluszcz:commit` skill. Message:

```
feat(iam): let the deploy role update the function directly

deploy-lambda.yml is moving from "upload and let LambdUpdate notice" to
calling UpdateFunctionCode itself. GetFunction backs the waiter that
confirms the new code went active.
```

---

### Task 5: Add the update step to `deploy-lambda.yml` and cut v2

**Repo:** `/Users/jacob/Documents/Programs/github-utils`

**Blocked by:** Tasks 1–4 **applied**, not merely merged. A caller that bumps its pin before its role has the grant gets `AccessDeniedException` on its next deploy.

**Files:**
- Modify: `.github/workflows/deploy-lambda.yml:54-55`
- Modify: `README.md:243,250,259,268-274`
- Modify: `CHANGELOG.md` (new entry at the top, under the `# Changelog` heading)

**Interfaces:**
- Consumes: the IAM grants from Tasks 1–4.
- Produces: tag `v2`, whose `deploy-lambda.yml` uploads and then updates. `v1` keeps its upload-only behavior for LambdUpdate, which never migrates.

- [ ] **Step 1: Replace the deploy step**

`.github/workflows/deploy-lambda.yml` currently ends:

```yaml
      - name: Deploy Lambda
        run: aws s3 cp "$PROJECT.zip" "s3://$AWS_BUCKET/"
```

Replace those two lines with:

```yaml
      - name: Upload Package
        run: aws s3 cp "$PROJECT.zip" "s3://$AWS_BUCKET/"

      - name: Update Function Code
        env:
          FUNCTION_NAME: ${{ inputs.project }}
        run: |
          for attempt in 1 2 3; do
            if err=$(aws lambda update-function-code \
              --function-name "$FUNCTION_NAME" \
              --s3-bucket "$AWS_BUCKET" \
              --s3-key "$PROJECT.zip" \
              --no-cli-pager 2>&1 >/dev/null); then
              break
            fi
            printf '%s\n' "$err" >&2
            case "$err" in
              *ResourceConflictException*)
                if [ "$attempt" -eq 3 ]; then
                  exit 1
                fi
                sleep $(( 1 << (attempt - 1) ))
                ;;
              *) exit 1 ;;
            esac
          done
          aws lambda wait function-updated-v2 --function-name "$FUNCTION_NAME"
```

Three things to preserve exactly:

- `2>&1 >/dev/null` in that order captures stderr into `err` and discards stdout. Reversing it captures the wrong stream.
- The `*)` arm exits on the first attempt for anything that is not a conflict, so a missing IAM grant surfaces as `AccessDeniedException` immediately rather than 3 seconds later.
- The step name changes from "Deploy Lambda" to "Upload Package" because "Deploy Lambda" followed by "Update Function Code" reads backwards. Step names are not status checks, so no caller is affected.

Do **not** touch `concurrency.group` — no new input distinguishes calls.

- [ ] **Step 2: Lint, and read the shellcheck output**

```bash
cd /Users/jacob/Documents/Programs/github-utils
uv run pre-commit run --all-files
```

Expected: all hooks pass, `Lint GitHub Actions workflow files` included — `actionlint` runs `shellcheck` over `run:` blocks, so this is the real gate on the script. If shellcheck flags `err` as possibly unused or objects to the `case` globs, fix the script rather than adding a `# shellcheck disable`.

- [ ] **Step 3: Update the README**

In the multi-region Lambda example block, bump all three pins in *that block only* — `rust-ci.yml@v1` → `@v2` (line 243), `lambda-package.yml@v1` → `@v2` (line 250), `deploy-lambda.yml@v1` → `@v2` (line 259). Leave the `claude`, `claude-code-review`, `auto-merge`, `node-ci`, `python-ci`, and `minify-and-upload` examples at `@v1`: those are still correct for `v1` callers, and `v1` keeps moving for backward-compatible fixes.

Then replace the paragraph at 268-274:

```markdown
`lambda-package.yml` produces `<project>.zip` (from a `lambda` binary) as artifact
`package`. `deploy-lambda.yml` assumes `${project}.github-deploy` (or
`${project}.github-deploy.${region}` when `regional: true`), copies the zip to
`s3://code-${account}-${region}-an/`, then calls `UpdateFunctionCode` on the
function named by `project` and waits for it to go active. The role therefore
needs three permissions: `s3:PutObject` on the object, and
`lambda:UpdateFunctionCode` plus `lambda:GetFunction` (which backs the waiter) on
the function. Each `deploy-*` job **must** grant `id-token: write` and pass the
`aws-account-id` secret. Repeat the `deploy` job per region for multi-region
repos — each region gets its own concurrency group (see "Concurrency"), so the
regions do not cancel each other.
```

- [ ] **Step 4: Add the CHANGELOG entry**

At the top of `CHANGELOG.md`, directly under `# Changelog`, dated the day you ship:

```markdown
## v2 — YYYY-MM-DD (Deploy updates the function)

`deploy-lambda.yml` now calls `UpdateFunctionCode` after copying the zip to the
code bucket, and waits for the function to go active, so a failed deploy reddens
CI instead of surfacing as a log line in someone else's Lambda. It retries
`ResourceConflictException` up to three times with 1s/2s backoff and fails
immediately on anything else.

**Breaking:** the `${project}.github-deploy` role now needs
`lambda:UpdateFunctionCode` and `lambda:GetFunction` on the target function in
addition to `s3:PutObject`. Grant those before bumping a caller's pin to `@v2`.
The function name is `project`; callers whose function is named differently need
a change here first.

This retires `LambdUpdate`, the Lambda that watched the code bucket for `.zip`
objects and called `UpdateFunctionCode` on the caller's behalf. Its
`function.names` object-metadata fan-out — one artifact updating several
functions — has no replacement, because no caller ever used it.
```

- [ ] **Step 5: Commit and open the PR**

Use the `jluszcz:commit` skill, then open a PR. This branch already carries the spec and this plan, so the PR covers all three.

- [ ] **Step 6: Merge, then cut the tag [you]**

```bash
cd /Users/jacob/Documents/Programs/github-utils
git switch main && git pull
scripts/release.py --breaking --dry-run -m "deploy-lambda.yml updates the function itself"
```

Expected dry-run output: `git tag -a v2 <sha> -m "v2: ..."` and `git push origin v2` — a new tag, no `-f`. Confirm the SHA is the merge commit, then rerun without `--dry-run`.

- [ ] **Step 7: Confirm v2 exists and v1 is untouched**

```bash
git ls-remote --tags origin | grep -E 'v[12]$'
```

Expected: both `v1` and `v2`. `v1` must still point at the pre-merge SHA — LambdUpdate stays on it through Task 10.

- [ ] **Step 8: Expect Dependabot noise in unrelated repos**

Roughly a dozen other repos pin `@v1` for `rust-ci`, `node-ci`, `python-ci`, `claude`, `claude-code-review`, `auto-merge`, or `minify-and-upload`. Their Dependabot `github-actions` ecosystem tracks the reusable-workflow ref, so they will each open a `@v1` → `@v2` PR. None of those workflows changed, so `v2` is a no-op for them and the PRs can be merged or ignored at will.

The four repos in Tasks 6–9 need attention, because **all four auto-merge Dependabot PRs**. Each carries a `.github/workflows/auto-merge.yml` calling the shared `auto-merge.yml@v1`, which runs `gh pr merge --auto --squash` for any `dependabot[bot]` PR, and each has a `github-actions` ecosystem on a **monthly** schedule grouped as `all-actions` with pattern `*`.

Two consequences:

- The `@v1` → `@v2` bump will arrive bundled with unrelated action bumps in one grouped PR, and will merge itself once checks pass. It cannot be reviewed in isolation.
- That grouped PR can migrate all four repos at roughly the same time, which defeats the LogStreamGC-first sequencing in Tasks 6–9.

This is safe rather than dangerous — Tasks 1–4 are applied before this task, so any repo that auto-migrates already has its IAM grant, which is exactly why the IAM stage comes first. But to keep the staged verification, do Tasks 6–9 by hand soon after cutting the tag rather than waiting for the monthly run. If Dependabot beats you to a repo, treat its merged PR as that task's Step 2 and go straight to the verification step.

---

### Task 6: Migrate LogStreamGC to v2 and verify a real deploy

**Repo:** `/Users/jacob/Documents/Programs/LogStreamGC`

**Blocked by:** Tasks 1 and 5.

First migration on purpose: LogStreamGC is the only two-region caller and one of two passing `regional: true`, so it exercises the most surface. Do not start Tasks 7–9 until this one's deploy is verified green.

**Files:**
- Modify: `.github/workflows/ci.yml:40,54`

**Interfaces:**
- Consumes: the IAM grant from Task 1 (both regions), tag `v2` from Task 5.
- Produces: proof the step works against a real function, including the `regional: true` role-name path.

- [ ] **Step 1: Record the current LastModified [you]**

Before deploying, so Step 4 has something to compare against:

```bash
aws lambda get-function --function-name log-stream-gc --region us-east-1 \
  --query 'Configuration.LastModified' --output text
```

- [ ] **Step 2: Bump both pins**

In `.github/workflows/ci.yml`, both the `deploy-us-east-1` and `deploy-us-east-2` jobs:

```yaml
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v2
```

Leave `rust-ci.yml@v1` and `lambda-package.yml@v1` alone — neither changed, and they are still on `v1`.

- [ ] **Step 3: Commit, PR, merge**

Use the `jluszcz:commit` skill. Message:

```
ci: update the function from CI instead of via LambdUpdate

deploy-lambda.yml@v2 calls UpdateFunctionCode after uploading, so a
failed deploy fails the job. The IAM grant it needs is already applied.
```

Merging to `main` triggers the deploy. Dependabot may have already opened this bump — reuse that PR if so.

- [ ] **Step 4: Watch the run and verify both regions [you]**

```bash
gh run watch --repo jluszcz/LogStreamGC
```

Expected: both `deploy-us-east-1` and `deploy-us-east-2` green, each with an `Update Function Code` step. Then:

```bash
for r in us-east-1 us-east-2; do
  aws lambda get-function --function-name log-stream-gc --region "$r" \
    --query 'Configuration.{Region:`'"$r"'`,LastModified:LastModified,Status:LastUpdateStatus}'
done
```

Expected: `LastModified` newer than Step 1's value and `LastUpdateStatus: Successful` in both regions.

During this window LambdUpdate is still subscribed to the bucket and also updates the function from the same key. That is expected and harmless — identical bytes, and the retry absorbs any `ResourceConflictException`. If the step log shows one retry and then success, that is the two paths colliding, not a bug.

- [ ] **Step 5: Update the deployment docs**

`CLAUDE.md:73-76` describes deploys generically ("auto-deploys to multiple AWS regions ... via GitHub Actions") and stays accurate. No edit needed — confirm by reading it, don't skip on faith.

---

### Task 7: Migrate JakeSky-rs to v2

**Repo:** `/Users/jacob/Documents/Programs/JakeSky-rs`

**Blocked by:** Tasks 4 and 6.

**Files:**
- Modify: `.github/workflows/ci.yml:40`

**Interfaces:**
- Consumes: the IAM grant from Task 4, tag `v2` from Task 5.
- Produces: nothing later tasks read, beyond counting toward Task 10's precondition.

- [ ] **Step 1: Record the current LastModified [you]**

```bash
aws lambda get-function --function-name jakesky --region us-east-1 \
  --query 'Configuration.LastModified' --output text
```

- [ ] **Step 2: Bump the pin**

```yaml
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v2
```

- [ ] **Step 3: Commit, PR, merge**

Use the `jluszcz:commit` skill. Message:

```
ci: update the function from CI instead of via LambdUpdate

deploy-lambda.yml@v2 calls UpdateFunctionCode after uploading, so a
failed deploy fails the job. The IAM grant it needs is already applied.
```

- [ ] **Step 4: Verify [you]**

```bash
gh run watch --repo jluszcz/JakeSky-rs
aws lambda get-function --function-name jakesky --region us-east-1 \
  --query 'Configuration.{LastModified:LastModified,Status:LastUpdateStatus}'
```

Expected: green `deploy` job; `LastModified` newer than Step 1; `LastUpdateStatus: Successful`.

- [ ] **Step 5: Check the docs**

`CLAUDE.md:26-27` says CI "packages and deploys the Lambda via the shared `lambda-package` and `deploy-lambda` workflows" — still true. No edit.

---

### Task 8: Migrate mbtalerts to v2 and correct its deployment docs

**Repo:** `/Users/jacob/Documents/Programs/mbtalerts`

**Blocked by:** Tasks 3 and 6.

This is the one caller whose docs name LambdUpdate explicitly, so the doc fix ships with the pin bump.

**Files:**
- Modify: `.github/workflows/ci.yml:43`
- Modify: `CLAUDE.md:95-98`

**Interfaces:**
- Consumes: the IAM grant from Task 3, tag `v2` from Task 5.
- Produces: nothing later tasks read.

- [ ] **Step 1: Record the current LastModified [you]**

```bash
aws lambda get-function --function-name mbtalerts --region us-east-2 \
  --query 'Configuration.LastModified' --output text
```

- [ ] **Step 2: Bump the pin**

```yaml
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v2
```

- [ ] **Step 3: Fix the deployment paragraph**

`CLAUDE.md` currently says:

```markdown
`mbtalerts.tf` provisions the Lambda, which EventBridge invokes on a `rate(3 hours)` schedule. On a push to `main`, CI
packages the `lambda` binary and uploads `mbtalerts.zip` to the us-east-2 code bucket — it does **not** call
`update-function-code`; the LambdUpdate watcher picks the object up and updates the function. Terraform is **not** run
by CI.
```

Replace with:

```markdown
`mbtalerts.tf` provisions the Lambda, which EventBridge invokes on a `rate(3 hours)` schedule. On a push to `main`, CI
packages the `lambda` binary, uploads `mbtalerts.zip` to the us-east-2 code bucket, and calls `update-function-code`
itself via the shared `deploy-lambda` workflow. Terraform is **not** run by CI.
```

Match the file's existing wrap width — it wraps at 120 columns, not 80.

- [ ] **Step 4: Commit, PR, merge**

Use the `jluszcz:commit` skill. The doc fix belongs in the same commit as the pin bump — it describes exactly this change. Message:

```
ci: update the function from CI instead of via LambdUpdate

deploy-lambda.yml@v2 calls UpdateFunctionCode after uploading, so a
failed deploy fails the job. The IAM grant it needs is already applied.
CLAUDE.md described the watcher by name and is corrected here.
```

- [ ] **Step 5: Verify [you]**

```bash
gh run watch --repo jluszcz/mbtalerts
aws lambda get-function --function-name mbtalerts --region us-east-2 \
  --query 'Configuration.{LastModified:LastModified,Status:LastUpdateStatus}'
```

Expected: green `deploy` job; `LastModified` newer than Step 1; `LastUpdateStatus: Successful`.

---

### Task 9: Migrate ListOfLists-rs to v2

**Repo:** `/Users/jacob/Documents/Programs/ListOfLists-rs`

**Blocked by:** Tasks 2 and 6.

**Files:**
- Modify: `.github/workflows/ci.yml:43`

**Interfaces:**
- Consumes: the IAM grant from Task 2, tag `v2` from Task 5.
- Produces: the last precondition for Task 10.

- [ ] **Step 1: Record the current LastModified [you]**

```bash
aws lambda get-function --function-name list-of-lists --region us-east-2 \
  --query 'Configuration.LastModified' --output text
```

- [ ] **Step 2: Bump the pin**

```yaml
    uses: jluszcz/github-utils/.github/workflows/deploy-lambda.yml@v2
```

- [ ] **Step 3: Commit, PR, merge**

Use the `jluszcz:commit` skill. Message:

```
ci: update the function from CI instead of via LambdUpdate

deploy-lambda.yml@v2 calls UpdateFunctionCode after uploading, so a
failed deploy fails the job. The IAM grant it needs is already applied.
```

Note this repo's CI `paths:` filter — pushes that touch only `Cargo**`, `src/**/*.rs`, `index.template`, or `.github/workflows/ci.yml` trigger it. A workflow-file change qualifies, so merging this PR does deploy.

- [ ] **Step 4: Verify [you]**

```bash
gh run watch --repo jluszcz/ListOfLists-rs
aws lambda get-function --function-name list-of-lists --region us-east-2 \
  --query 'Configuration.{LastModified:LastModified,Status:LastUpdateStatus}'
```

Expected: green `deploy` job; `LastModified` newer than Step 1; `LastUpdateStatus: Successful`.

- [ ] **Step 5: Check the docs**

`CLAUDE.md:22` says CI "packages and deploys the Lambda to `us-east-2` via the shared `lambda-package` and `deploy-lambda` workflows" — still true. No edit.

---

### Task 10: Remove the S3 bucket notification

**Repo:** `/Users/jacob/Documents/Programs/LambdUpdate`

**Blocked by:** Tasks 6, 7, 8, and 9 all verified. Confirm before starting:

```bash
for r in LogStreamGC JakeSky-rs mbtalerts ListOfLists-rs; do
  echo -n "$r: "
  gh api "repos/jluszcz/$r/contents/.github/workflows/ci.yml" --jq '.content' \
    | base64 -d | grep -o 'deploy-lambda.yml@v[0-9]*' | sort -u | tr '\n' ' '
  echo
done
```

Expected: every line shows `deploy-lambda.yml@v2` and nothing else. Any `@v1` means that repo still depends on the notification you are about to delete.

**Files:**
- Modify: `lambdupdate.tf:93-109`

**Interfaces:**
- Consumes: all four callers on `@v2`.
- Produces: nothing writes to Lambda from S3 events any more. Double updates stop here.

- [ ] **Step 1: Delete the notification and the invoke permission**

Remove both resources from `lambdupdate.tf`:

```hcl
resource "aws_s3_bucket_notification" "notification" {
  bucket = data.aws_s3_bucket.code_bucket.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.lambdupdate.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".zip"
  }
}

resource "aws_lambda_permission" "allow_bucket" {
  statement_id  = "lambdupdate-allow-exec-from-s3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lambdupdate.arn
  principal     = "s3.amazonaws.com"
  source_arn    = data.aws_s3_bucket.code_bucket.arn
}
```

Leave everything else — the function, roles, policies, and log group come down in Task 11.

- [ ] **Step 2: Verify the plan in us-east-1 [you]**

```bash
cd /Users/jacob/Documents/Programs/LambdUpdate
. env-us_east_1
terraform plan
```

Expected: exactly two destroys — `aws_s3_bucket_notification.notification` and `aws_lambda_permission.allow_bucket`. Nothing else. The code bucket is a `data` source, so the bucket itself is never at risk; only its notification configuration is managed here.

- [ ] **Step 3: Apply both regions [you]**

```bash
. env-us_east_1 && terraform apply
. env-us_east_2 && terraform apply
```

- [ ] **Step 4: Confirm the notification is gone [you]**

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
for r in us-east-1 us-east-2; do
  echo "== $r"
  aws s3api get-bucket-notification-configuration \
    --bucket "code-$ACCOUNT-$r-an" --region "$r"
done
```

Expected: an empty configuration (`{}`) in both regions. If either still lists a `LambdaFunctionConfigurations` entry, the apply did not take.

- [ ] **Step 5: Commit**

Use the `jluszcz:commit` skill. Message:

```
feat: stop watching the code bucket

Every caller of deploy-lambda.yml is on @v2, which calls
UpdateFunctionCode itself. The notification and the S3 invoke permission
have nothing left to trigger.
```

**Reverting this** means restoring both resources and re-applying, not recreating the notification by hand — the whole notification configuration for the bucket is managed by this resource.

---

### Task 11: Destroy and archive LambdUpdate

**Repo:** `/Users/jacob/Documents/Programs/LambdUpdate`

**Blocked by:** Task 10.

LambdUpdate never migrates to `@v2` — it stays on `@v1`, whose `deploy-lambda.yml` only uploads. Since Task 10, its own deploys have been no-ops. That is fine; this task deletes it.

**Files:**
- Modify: `README.md` (retirement note at the top)
- Destroy: all resources in `lambdupdate.tf`, both workspaces

**Interfaces:**
- Consumes: the notification removal from Task 10.
- Produces: nothing. This is the last task.

- [ ] **Step 1: Add the retirement note**

At the top of `README.md`, immediately after the title:

```markdown
> **Retired 2026-08-02.** Lambda code deploys no longer go through this
> service. `deploy-lambda.yml` in [jluszcz/github-utils][gh-utils] uploads the
> artifact to the code bucket and calls `UpdateFunctionCode` itself. The
> rationale is in that repo, under
> `docs/superpowers/specs/2026-08-02-lambdupdate-retirement-design.md`.
>
> The one capability without a replacement is the `function.names` object
> metadata key, which pointed a single artifact at several functions. No
> project used it.

[gh-utils]: https://github.com/jluszcz/github-utils
```

Adjust the date to the day you actually archive.

- [ ] **Step 2: Commit and merge the note**

Use the `jluszcz:commit` skill. Message:

```
docs: mark LambdUpdate retired

deploy-lambda.yml calls UpdateFunctionCode directly as of github-utils
v2. Nothing invokes this service any more.
```

Merge before destroying — once the repo is archived it is read-only.

- [ ] **Step 3: Review what destroy will remove [you]**

```bash
cd /Users/jacob/Documents/Programs/LambdUpdate
. env-us_east_1
terraform plan -destroy
```

Expected, per region: the Lambda function, `aws_cloudwatch_log_group.lambdupdate`, the `lambdupdate.lambda.<region>` role with its three policies and attachments, and the `lambdupdate.github-deploy.<region>` role, policy, and attachment. The code bucket must **not** appear — it is a `data` source. If a bucket shows up as being destroyed, stop immediately.

The log group goes with it. Retention is 7 days, so there is nothing worth exporting; if you want the last week of invocation logs, pull them before this step.

- [ ] **Step 4: Destroy both regions [you]**

```bash
. env-us_east_1 && terraform destroy
. env-us_east_2 && terraform destroy
```

- [ ] **Step 5: Delete the workspaces and state [you]**

```bash
terraform workspace select default
terraform workspace delete lambdupdate_us-east-1
terraform workspace delete lambdupdate_us-east-2
```

Then remove the leftover state objects under key `lambdupdate` in `s3://jluszcz-tf-state`. List before deleting:

```bash
aws s3 ls --recursive s3://jluszcz-tf-state/ --region us-east-2 | grep lambdupdate
```

Delete only paths containing `lambdupdate`. Other projects share this bucket.

- [ ] **Step 6: Confirm the function is gone [you]**

```bash
for r in us-east-1 us-east-2; do
  aws lambda get-function --function-name lambdupdate --region "$r" 2>&1 | tail -1
done
```

Expected: `ResourceNotFoundException` in both regions.

- [ ] **Step 7: Archive the repo [you]**

```bash
gh repo archive jluszcz/LambdUpdate
```

This is reversible (`gh repo unarchive`) but stops CI, Dependabot, and pushes. Do it only after Step 6 passes.

- [ ] **Step 8: Confirm nothing still references the retired workflow path**

```bash
cd /Users/jacob/Documents/Programs
grep -rn -i "lambdupdate" --include="*.md" --include="*.tf" --include="*.yml" \
  LogStreamGC ListOfLists-rs mbtalerts JakeSky-rs github-utils
```

Expected: only historical references — `github-utils/CHANGELOG.md` (both the old v1 entry at line ~53 and the new v2 entry) and the spec and plan under `github-utils/docs/superpowers/`. Any hit in a `.tf` or a workflow file is a live reference that was missed.

---

## Rollback

Each task reverts independently:

- **Tasks 1–4:** revert the commit, `terraform apply`. Safe at any time before the matching repo moves to `@v2`.
- **Task 5:** `v1` is untouched, so any caller can be pinned back to `@v1` and will deploy exactly as before — *provided* the bucket notification still exists. That is true until Task 10.
- **Tasks 6–9:** revert the pin to `@v1`.
- **Task 10:** restore both resources and re-apply. This is the point of no easy return: after it, `@v1` no longer deploys anything, so rolling a caller back means rolling Task 10 back first.
- **Task 11:** `gh repo unarchive` restores the repo, but the infrastructure is gone and would need `terraform apply` against fresh state.
