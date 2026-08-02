# Retire LambdUpdate: deploy-lambda.yml updates functions directly

**Date:** 2026-08-02
**Status:** Approved, not yet implemented

## Problem

`deploy-lambda.yml` copies `<project>.zip` to `s3://code-<account>-<region>-an/`
and stops there. A separate Rust Lambda, [LambdUpdate], is subscribed to that
bucket's `s3:ObjectCreated:*` events with a `.zip` suffix filter; it reads the
target function names from the object and calls `UpdateFunctionCode`.

That indirection costs a repository, two Terraform workspaces, a per-region
Lambda and log group, and an IAM role holding `lambda:UpdateFunctionCode` on
`arn:aws:lambda:<region>:<account>:function:*`. It buys one capability the
workflow lacks: a single artifact fanning out to several functions, via a
`function.names` object-metadata key.

Nothing uses that capability. Every caller is 1:1, and the function name always
equals the `project` input:

| Repo | `project` | `function_name` | Regions |
|---|---|---|---|
| LambdUpdate | `lambdupdate` | `lambdupdate` | us-east-1, us-east-2 |
| LogStreamGC | `log-stream-gc` | `log-stream-gc` | us-east-1, us-east-2 |
| ListOfLists-rs | `list-of-lists` | `list-of-lists` | us-east-2 |
| mbtalerts | `mbtalerts` | `mbtalerts` | us-east-2 |
| JakeSky-rs | `jakesky` | `jakesky` | us-east-1 |

Those five are the complete set of `deploy-lambda.yml` callers. `MovieList`,
`StarList`, and `BurgerList` call `minify-and-upload.yml` only and are untouched
by this work.

[LambdUpdate]: https://github.com/jluszcz/LambdUpdate

## End state

`deploy-lambda.yml` uploads the zip **and** calls `update-function-code` itself.
LambdUpdate — the Lambda, its Terraform, the bucket notification, and the
account-wide `function:*` grant — is destroyed and the repo archived. Each
project's `github-deploy` role gains `lambda:UpdateFunctionCode` scoped to its
own function.

What goes away with it:

- The `function.names` fan-out. No caller sets it.
- The `.zip` key suffix as a deploy trigger.
- An implicit privilege escalation: today anything holding `s3:PutObject` on the
  code bucket can replace any Lambda's code in the account.

What is deliberately kept:

- The `aws s3 cp` to the code bucket. Terraform's `aws_lambda_function`
  resources still reference `s3_bucket`/`s3_key` to *create* a function, so the
  bucket stays in the deploy path and keeps a copy of each deployed artifact.

## Design

### `deploy-lambda.yml`

No new inputs. `FUNCTION_NAME` is `inputs.project`, so nothing new distinguishes
one call from another and `concurrency.group` is unchanged. One step is appended
after the existing `aws s3 cp`:

```yaml
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

Three decisions are embedded here:

**Only `ResourceConflictException` retries.** The AWS CLI's own retry modes
cover throttling and transient transport failures; `ResourceConflictException`
is a modeled client error and is never retried. Matching LambdUpdate, the step
retries just that one, so a misconfigured role fails on the first attempt with
its real error rather than three attempts later. Backoff is 1s then 2s —
LambdUpdate's 500ms/1s was sized against a 5s Lambda timeout that no longer
applies.

**The wait is after, not before.** Waiting first does not remove the race: a
concurrent update can begin between the wait returning and the call landing.
Waiting after turns "the API accepted the update" into "the function reached
`Successful`", so a code push that lands but fails to activate reddens CI
instead of passing silently.

**`wait function-updated-v2` polls `GetFunction`**, so the deploy role needs
`lambda:GetFunction` in addition to `lambda:UpdateFunctionCode`.

### Per-repo IAM

Four repos. LambdUpdate is excluded — see stage 5. One statement is added to the
existing GitHub-deploy policy document:

```hcl
  statement {
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
    resources = [aws_lambda_function.<name>.arn]
  }
```

The existing `s3:PutObject` statement also needs `s3:GetObject` added to its
`actions` list. `aws lambda update-function-code --s3-bucket/--s3-key` has
Lambda fetch the artifact using the *caller's* credentials, not the function's
execution role, so the role doing the deploy — not just the function being
updated — must be able to read the object it just wrote.

This was missed in the original version of this design: LambdUpdate's own
`s3` policy (`lambdupdate.tf:76-81`) already holds `s3:GetObject` on the code
bucket, because it was LambdUpdate calling `UpdateFunctionCode` and so
LambdUpdate that needed to read the object. Moving the API call to the
caller's role in this design moves that read requirement with it — a detail
this design missed until a real deploy hit `AccessDeniedException`.

| Repo | File | Policy document | Function resource |
|---|---|---|---|
| LogStreamGC | `log-stream-gc.tf` | `github` | `aws_lambda_function.log_stream_gc` |
| ListOfLists-rs | `shared/main.tf` | `github_deploy` | `aws_lambda_function.lambda` |
| mbtalerts | `mbtalerts.tf` | `github` | `aws_lambda_function.mbtalerts` |
| JakeSky-rs | `jakesky.tf` | `github` | `aws_lambda_function.jakesky` |

LogStreamGC is applied in both us-east-1 and us-east-2; the other three are
single-region.

### Versioning: cut `v2`

The new step fails on any caller whose role lacks the two Lambda permissions, so
this is a breaking change to `deploy-lambda.yml`'s contract:
`scripts/release.py --breaking`, and a `CHANGELOG.md` heading in this repo's
documented form, `## v2 — YYYY-MM-DD (short title)`, dated the day it ships.

Cutting a major rather than moving `v1` also supplies the staged rollout the
moving tag cannot. Each repo bumps its own `uses:` pin (Dependabot opens the
PR), so the window in which both LambdUpdate and the workflow update the same
function is per-repo and bounded, instead of hitting all five at once.

The other ~11 repos pinned at `@v1` will also receive Dependabot `@v1`→`@v2`
PRs. `v2` is a no-op for them; they can merge at any time.

## Rollout

Each stage leaves the system working and is revertable on its own.

**1. IAM grants.** The four Terraform changes above, applied (LogStreamGC twice).
Grants are inert until something assumes the role and calls the API, so this
stage changes no behavior.

**2. github-utils PR.** The new step, the README paragraph, the `CHANGELOG.md`
entry. Merge, then `scripts/release.py --breaking -m "<what changed>"`.

**3. Bump pins, one repo at a time.** LogStreamGC first: it is the only
two-region caller and the only one passing `regional: true`, so it exercises the
most surface. Confirm with

```sh
aws lambda get-function --function-name log-stream-gc \
  --query 'Configuration.{LastModified:LastModified,Status:LastUpdateStatus}'
```

before moving to JakeSky-rs, mbtalerts, and ListOfLists-rs. Throughout this
stage both LambdUpdate and the workflow update the function from the same key
with identical bytes; the retry absorbs the collision, and the worst case is one
extra `UpdateFunctionCode` call.

**4. Remove the trigger.** Delete `aws_s3_bucket_notification.notification` and
`aws_lambda_permission.allow_bucket` from `lambdupdate.tf`; apply in both
regions. Double updates stop here. The bucket is a data source, so only the
notification configuration is affected.

**5. Retire LambdUpdate.** It never migrates to `v2` — it stays on `v1`, whose
`deploy-lambda.yml` still only uploads, and so simply stops deploying at stage 4.
That is acceptable because the next actions are: `terraform destroy` in both
workspaces, delete the `lambdupdate_us-east-1` and `lambdupdate_us-east-2`
workspaces and the `lambdupdate` state key, add a retirement note to the repo's
README pointing at `github-utils`, and archive the repo. The CloudWatch log
group is destroyed with it; retention is 7 days and there is nothing to
preserve.

## Documentation

- **`github-utils/README.md`** — the `deploy-lambda.yml` paragraph currently
  ends at "copies the zip to `s3://code-${account}-${region}-an/`". It must say
  the workflow then updates the function, and that the role needs
  `s3:PutObject`, `lambda:UpdateFunctionCode`, and `lambda:GetFunction`.
- **`github-utils/CHANGELOG.md`** — `## v2 — <date>` entry, in the same PR as
  the workflow change.
- **`mbtalerts/CLAUDE.md`** (line 97) is the only consumer doc that names the
  watcher: "the LambdUpdate watcher picks the object up and updates the
  function." LogStreamGC, ListOfLists-rs, and JakeSky-rs describe their deploys
  generically and need no edit.

## Verification

`uv run pre-commit run --all-files` in github-utils covers the new step —
`actionlint` shellchecks `run:` blocks, so quoting and the `case` statement are
linted before commit.

Beyond that there is no unit-testable surface. The step's correctness is
observable only against the Lambda API, so the gate for each repo in stage 3 is
a real deploy watched end to end, not a green CI badge. The implementation plan
should state this explicitly rather than treating stage 3 as a mechanical pin
bump.

## Rejected alternatives

**Skip S3, `update-function-code --zip-file`.** Removes the bucket from the
deploy path, but Terraform still needs an object in S3 to create a function, so
every new project would need a manual first upload. Also caps the artifact at
the 50 MB request limit.

**Move `v1` instead of cutting `v2`.** All five callers are under our control
and the IAM grants land first, so no caller would ever have seen a broken `v1`.
Rejected because a major gives per-repo pacing for free, and the new IAM
requirement is a genuine change to the workflow's contract.

**Add a `function-name` input.** Nothing needs it — the five callers all have
`function_name == project`. It would also have to join `concurrency.group` per
`CLAUDE.md`. Add it the day a repo actually diverges.

**Remove the bucket notification before shipping the workflow step.** Avoids
double updates entirely, but opens a window in which a push to `main` uploads an
artifact that nothing deploys. Double updates are harmless and the retry already
handles them; a silently skipped deploy is not.
