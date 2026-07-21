# Lambda Deploy Migration

## Goal

Uplift the packaging and deployment plumbing shared across the 5 Rust/Lambda
repos into reusable workflows in `github-utils`, completing the CI migration that
deliberately deferred these repos. After this change every Lambda repo's
`ci.yml` is a thin orchestrator: shared CI, shared packaging, shared per-region
deploy — no inlined build/package/deploy steps, and the duplicated local
`deploy-lambda.yml` copies are gone. The deploy IAM roles are standardized to a
single `-deploy`-suffixed convention.

Scope is the 5 Rust/Lambda repos only: **JakeSky-rs, LambdUpdate,
ListOfLists-rs, LogStreamGC, mbtalerts**. Non-Lambda deploys
(`jluszcz.com/minify-and-upload-to-s3.yml`, `ListOfLists-rs/update-index-template.yml`,
`skills/bump-version.yml`) are out of scope.

## Current state (what we're replacing)

Each repo's `ci.yml` has one `build` job doing build/test/lint **and**
release-package + upload-artifact (`if: github.event_name == 'push'`), plus one
or more `deploy` jobs (`needs: build`). The package step is byte-identical
everywhere (only `PROJECT`/target vary):

```
cargo build --release --target $T
cp target/$T/release/lambda bootstrap
zip -j $PROJECT.zip bootstrap
# upload-artifact name=package, retention-days: 1
```

Deploy is uniform except three axes — bucket `code-${account}-${region}-an`,
`aws-actions/configure-aws-credentials@v6.2.1`, session `github-deploy`, and
artifact `package` are all identical; regions, region source, and IAM role name
differ. LambdUpdate & LogStreamGC already factor deploy into a local
`deploy-lambda.yml` reusable — the basis for the shared one.

### The IAM role inconsistency

Each repo's own Terraform (`<project>.tf`, or `shared/main.tf` for ListOfLists)
defines a GitHub OIDC deploy role — an `aws_iam_policy` + `aws_iam_role` +
`aws_iam_role_policy_attachment` granting `s3:PutObject` on `<project>.zip`,
trusted for `repo:jluszcz/<Repo>:*`. The role **names** diverge:

| Repo | Current deploy role | TF file |
|---|---|---|
| ListOfLists-rs | `list-of-lists.github-deploy` | `shared/main.tf` |
| JakeSky-rs | `jakesky.github` | `jakesky.tf` |
| mbtalerts | `mbtalerts.github` | `mbtalerts.tf` |
| LambdUpdate | `lambdupdate.github.${region}` | `lambdupdate.tf` (per-region workspace) |
| LogStreamGC | `log-stream-gc.github.${region}` | `log-stream-gc.tf` (per-region workspace) |

ListOfLists already uses `-deploy` because it has a *second* GitHub role
(`list-of-lists.github-update`, for the out-of-scope index-template workflow) —
plain `.github` would be ambiguous. We adopt `-deploy` as the **canonical**
convention for exactly that reason: it unambiguously names the code-deploy role.

## Architecture

Two new reusable `workflow_call` workflows in `github-utils/.github/workflows/`,
composed with the existing `rust-ci.yml@v1`. Each Lambda repo's `ci.yml` becomes
three job types:

```yaml
jobs:
  ci:                # rust-ci.yml@v1 — build/test/lint; runs on push AND pull_request
  package:           # lambda-package.yml@v1 — needs: ci, if: push
  deploy-<region>:   # deploy-lambda.yml@v1 — needs: package, if: push, per region
```

`package` and `deploy-*` are whole-job `if: github.event_name == 'push'`, so on a
PR only `ci` runs (deploy plumbing cannot be exercised from a PR — see Rollout).

### `lambda-package.yml`

Isolates the release build from CI (keeps `rust-ci.yml` pure).

| Input | Type | Default | Purpose |
|---|---|---|---|
| `project` | string | *(required)* | zip filename (`<project>.zip`) |
| `target` | string | `aarch64-unknown-linux-musl` | Rust target triple |
| `runs-on` | string | `ubuntu-24.04-arm` | runner |

`permissions: contents: read`. Steps: checkout → install `musl-tools` +
`rustup target add <target>` → `Swatinem/rust-cache@v2` →
`cargo build --release --target <target>` →
`cp target/<target>/release/lambda bootstrap` → `zip -j <project>.zip bootstrap`
→ `actions/upload-artifact@v7` (name `package`, path `<project>.zip`,
`retention-days: 1`).

### `deploy-lambda.yml`

Generalizes the existing local reusable: `PROJECT` becomes an input, and the IAM
role name is standardized to `${project}.github-deploy` with an optional
`.${region}` suffix gated by a `regional` boolean.

| Input | Type | Default | Purpose |
|---|---|---|---|
| `aws-region` | string | *(required)* | deploy region |
| `project` | string | *(required)* | role/zip name |
| `regional` | boolean | `false` | append `.${aws-region}` to the role name |

Secret: `aws-account-id` (required). `permissions: id-token: write,
contents: read`. Steps: `actions/download-artifact@v8` (name `package`) →
`configure-aws-credentials@v6.2.1` → `aws s3 cp <project>.zip
s3://code-${aws-account-id}-${aws-region}-an/`.

Role expression:
```
role-to-assume: arn:aws:iam::${{ secrets.aws-account-id }}:role/${{ inputs.project }}.github-deploy${{ inputs.regional && format('.{0}', inputs.aws-region) || '' }}
```
`regional:false` → `${project}.github-deploy`; `regional:true` →
`${project}.github-deploy.${region}`.

### Per-repo caller parameters

| Repo | project | regions | regional | Target deploy role | New IAM role? |
|---|---|---|---|---|---|
| ListOfLists-rs | `list-of-lists` | us-east-2 | false | `list-of-lists.github-deploy` | **no — already exists** |
| LambdUpdate | `lambdupdate` | us-east-1, us-east-2 | true | `lambdupdate.github-deploy.${region}` | yes (per region) |
| LogStreamGC | `log-stream-gc` | us-east-1, us-east-2 | true | `log-stream-gc.github-deploy.${region}` | yes (per region) |
| JakeSky-rs | `jakesky` | us-east-1 | false | `jakesky.github-deploy` | yes |
| mbtalerts | `mbtalerts` | us-east-2 | false | `mbtalerts.github-deploy` | yes |

The `ci` job uses `rust-ci.yml@v1` with `runs-on: ubuntu-24.04-arm`,
`target: aarch64-unknown-linux-musl` (no `all-features`). Each repo keeps its own
`on:`/`permissions` block. LambdUpdate & LogStreamGC delete their local
`deploy-lambda.yml`. ListOfLists drops its `AWS_DEFAULT_REGION` secret usage
(region hardcoded to us-east-2 — confirm this matches the current secret). The
vestigial `id-token: write` on JakeSky/mbtalerts' old build job is dropped (only
deploy jobs need it).

## IAM change (per-repo Terraform)

The `-deploy` roles are created by **duplicating** each repo's existing `github`
deploy role in its own Terraform, then cleaning up the stale `.github` role after
the workflow is confirmed working. ListOfLists needs no change (already
`-deploy`). For the other four, add a `github_deploy` set of resources mirroring
the existing `github` ones — same assume-role policy (OIDC trust for
`repo:jluszcz/<Repo>:*`) and same `s3:PutObject` policy on `<project>.zip` —
named:

- `jakesky.github-deploy`, `mbtalerts.github-deploy` (non-regional)
- `lambdupdate.github-deploy.${var.aws_region}`,
  `log-stream-gc.github-deploy.${var.aws_region}` (regional, one per workspace)

ListOfLists' existing `github_deploy` blocks in `shared/main.tf` are the model
to copy.

**Ownership & sequencing:** the migration adds the duplicate `-deploy` role
resources to each repo's Terraform; **the user applies them** (`terraform apply`,
per-region for LambdUpdate/LogStreamGC). The new role must exist **before** that
repo's workflow PR merges (the post-merge push assumes it). After the deploy is
confirmed on the new role, the stale `.github` / `.github.${region}` role
resources are removed in a follow-up (**user-owned cleanup**). Per-project deploy
roles live only in each repo's Terraform — not in `AmazonWebServices/aws.tf`
(that holds just the account-level OIDC provider).

## Rollout — canary, then the rest

Deploy jobs run only on push-to-main, so a bug in the shared workflow surfaces as
a **failed real deploy**, not a red PR check. Sequence:

1. **Ship both workflows** in `github-utils` (PR; additive → move `v1`; README +
   CHANGELOG).
2. **Canary: LambdUpdate** — regional path + new-role process, the hardest case.
   Add + apply `lambdupdate.github-deploy.${region}` in both regions, migrate the
   workflow, merge, and watch the post-merge deploy to **both** regions succeed
   before proceeding.
3. **LogStreamGC** — same regional shape.
4. **JakeSky-rs** — first non-regional new-role case (validates the
   `${project}.github-deploy` role path); then **mbtalerts** (same shape).
5. **ListOfLists-rs (last, lowest risk)** — no IAM change; only the workflow swap
   and the us-east-2 hardcode.

Per non-ListOfLists repo: add + apply the `-deploy` role → migrate the workflow →
merge → confirm the post-merge deploy → user removes the stale `.github` role.
Every repo also gets its ruleset required check renamed to
`ci / Build, Test & Lint`.

## Success criteria

- `lambda-package.yml` and `deploy-lambda.yml` exist in `github-utils`, pass
  `actionlint`, documented in README + CHANGELOG, released on `v1`.
- All 5 Lambda repos run CI via `rust-ci.yml@v1`, package via
  `lambda-package.yml@v1`, and deploy via `deploy-lambda.yml@v1`; no repo retains
  inlined build/package/deploy steps or a local `deploy-lambda.yml`.
- Each repo's post-merge push deploys the artifact to the same bucket(s) as
  before, assuming the new `${project}.github-deploy[.${region}]` role.
- Each repo's ruleset requires `ci / Build, Test & Lint`.
- (User follow-up) stale `.github` / `.github.${region}` deploy roles removed.

## Deferred / out of scope

- Non-Lambda deploys (static-site S3 upload, index-template, version bump).
- The stale-role cleanup Terraform + apply (user-owned follow-up per repo).
- Optimizing away the separate release build (the `package` job recompiles in
  release; acceptable — `rust-cache` keeps the delta small).
