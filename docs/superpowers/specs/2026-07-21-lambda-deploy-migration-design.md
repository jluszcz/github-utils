# Lambda Deploy Migration

## Goal

Uplift the packaging and deployment plumbing shared across the 5 Rust/Lambda
repos into reusable workflows in `github-utils`, completing the CI migration that
deliberately deferred these repos. After this change every Lambda repo's
`ci.yml` is a thin orchestrator: shared CI, shared packaging, shared per-region
deploy — no inlined build/package/deploy steps, and the duplicated local
`deploy-lambda.yml` copies are gone.

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
differ (see the per-repo table below). LambdUpdate & LogStreamGC already factor
deploy into a local `deploy-lambda.yml` reusable — the basis for the shared one.

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

Isolates the release build from CI (the "separate package reusable" choice —
keeps `rust-ci.yml` pure).

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
`retention-days: 1`). `upload-artifact` needs no special permissions (Actions
runtime token).

### `deploy-lambda.yml`

Generalizes the existing local reusable: `PROJECT` becomes an input, and the IAM
role name is standardized to `${project}.github` with an optional `.${region}`
suffix gated by a `regional` boolean.

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
role-to-assume: arn:aws:iam::${{ secrets.aws-account-id }}:role/${{ inputs.project }}.github${{ inputs.regional && format('.{0}', inputs.aws-region) || '' }}
```
`regional:false` → `${project}.github`; `regional:true` →
`${project}.github.${region}`.

### Per-repo caller parameters

| Repo | project | regions | regional | Notes |
|---|---|---|---|---|
| LambdUpdate | `lambdupdate` | us-east-1, us-east-2 | true | delete local `deploy-lambda.yml` |
| LogStreamGC | `log-stream-gc` | us-east-1, us-east-2 | true | delete local `deploy-lambda.yml` |
| JakeSky-rs | `jakesky` | us-east-1 | false | — |
| mbtalerts | `mbtalerts` | us-east-2 | false | — |
| ListOfLists-rs | `list-of-lists` | us-east-2 | false | **new IAM role `list-of-lists.github` required**; drop `AWS_DEFAULT_REGION` secret |

The `ci` job uses `rust-ci.yml@v1` with `runs-on: ubuntu-24.04-arm`,
`target: aarch64-unknown-linux-musl` (no `all-features`). Each repo keeps its own
`on:`/`permissions` block. The vestigial `id-token: write` on JakeSky/mbtalerts'
old build job is dropped (only deploy jobs need it).

## IAM prerequisite (ListOfLists-rs)

ListOfLists currently assumes `list-of-lists.github-deploy` with the region from
`secrets.AWS_DEFAULT_REGION`. The standardized workflow assumes
`list-of-lists.github` in a hardcoded `us-east-2`. Before ListOfLists migrates, a
`list-of-lists.github` IAM role must exist mirroring the trust policy (GitHub
OIDC for `jluszcz/ListOfLists-rs`) and S3 permissions of the current
`.github-deploy` role. These per-project roles are **not** in
`AmazonWebServices/aws.tf` (that holds only the account-level OIDC provider);
the role lives in ListOfLists' own IaC or is managed manually. This role
creation is a prerequisite handoff, not part of the workflow PRs, and is why
ListOfLists is migrated last.

## Rollout — canary, then the rest

Deploy jobs run only on push-to-main, so a bug in the shared workflow surfaces as
a **failed real deploy**, not a red PR check. Sequence:

1. **Ship both workflows** in `github-utils` (PR; additive → move `v1`; README +
   CHANGELOG).
2. **Canary: LambdUpdate** — `regional:true`, existing roles, no IAM change.
   Migrate, merge, and watch the post-merge deploy to **both** regions succeed
   before proceeding.
3. **LogStreamGC** — same shape.
4. **JakeSky-rs**, **mbtalerts** — `regional:false`, existing `.github` roles.
5. **ListOfLists-rs (last)** — gated on the `list-of-lists.github` role existing.

Each repo: replace `ci.yml` (preserving its `on:`/`permissions`), delete the
local `deploy-lambda.yml` where present, rename the ruleset required check to
`ci / Build, Test & Lint`, and — for a Lambda repo — confirm the first
post-merge push deploys cleanly.

## Success criteria

- `lambda-package.yml` and `deploy-lambda.yml` exist in `github-utils`, pass
  `actionlint`, documented in README + CHANGELOG, released on `v1`.
- All 5 Lambda repos run CI via `rust-ci.yml@v1`, package via
  `lambda-package.yml@v1`, and deploy via `deploy-lambda.yml@v1`; no repo retains
  inlined build/package/deploy steps or a local `deploy-lambda.yml`.
- Each repo's post-merge push deploys the artifact to the same bucket(s) as
  before, from the same IAM role(s) (except ListOfLists, which moves to the new
  `list-of-lists.github` role in us-east-2).
- Each repo's ruleset requires `ci / Build, Test & Lint`.

## Deferred / out of scope

- Non-Lambda deploys (static-site S3 upload, index-template, version bump).
- Any consolidation of the deploy IAM roles beyond adding `list-of-lists.github`.
- Optimizing away the separate release build (the `package` job recompiles in
  release; acceptable — `rust-cache` keeps the delta small).
