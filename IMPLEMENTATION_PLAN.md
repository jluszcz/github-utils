# Shared "Minify and Upload" workflow

## Design

### Problem

`BurgerList`, `MovieList`, and `StarList` each carry a byte-identical
`.github/workflows/workflow.yml` that minifies a JSON list and uploads it to S3.
They differ in exactly three values:

| Repo | Source file | IAM role | S3 key |
|---|---|---|---|
| BurgerList | `burgerlist.json` | `burgerlist.github-update` | `burgerl.ist.json` |
| MovieList | `movielist.json` | `movielist.github-update` | `moviel.ist.json` |
| StarList | `starlist.json` | `starlist.github-update` | `starl.ist.json` |

Everything else — the `jq` filter, the bucket
(`list-of-lists-<account>-<region>-an`), permissions, and step order — is shared.
A fix (an action bump, a filter change) currently means three edits.

### Solution

Add `.github/workflows/minify-and-upload.yml` to `github-utils` as a reusable
`workflow_call` workflow, modeled on the existing `deploy-lambda.yml`: same
`contents: read` + `id-token: write` permissions, same SHA-pinned
`aws-actions/configure-aws-credentials`, same `<prefix>-<account>-<region>-an`
bucket composition, and an `aws-region` input plus an `aws-account-id` secret.

### Inputs

| Name | Kind | Example | Notes |
|---|---|---|---|
| `aws-region` | required input | `us-east-2` | Cannot come from a secret — see below |
| `project` | required input | `burgerlist` | Derives `${project}.json` and role `${project}.github-update` |
| `s3-key-prefix` | required input | `burgerl.ist` | Workflow appends `.json` |
| `bucket-prefix` | required input | `list-of-lists` | Composed to `<prefix>-<account>-<region>-an` |
| `aws-account-id` | required secret | — | Same as `deploy-lambda.yml` |

Two conventions are baked in rather than parameterized, because all three
consumers share them: the `jq` filter
(`.lists |= map(select(.hidden != true))`) and the IAM role suffix
(`.github-update`). A fourth consumer that breaks either convention is the
trigger to add an input, not a reason to add one now.

`aws-region` is an input rather than a secret because a reusable workflow's
`with:` block cannot reference the `secrets` context (only `github`, `needs`,
`inputs`, `vars`, `matrix`, `strategy`). All three callers pass the literal
`us-east-2`; `secrets.AWS_DEFAULT_REGION` stops being read by these repos.

### The workflow

```yaml
name: Minify and Upload

on:
  workflow_call:
    inputs:
      aws-region:    { required: true, type: string }
      project:       { required: true, type: string }
      s3-key-prefix: { required: true, type: string }
      bucket-prefix: { required: true, type: string }
    secrets:
      aws-account-id: { required: true }

permissions:
  contents: read
  id-token: write

concurrency:
  group: ${{ github.workflow }}-minify-and-upload-${{ inputs.project }}-${{ inputs.aws-region }}-${{ inputs.s3-key-prefix }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  upload:
    name: Minify and Upload
    runs-on: ubuntu-latest
    env:
      AWS_BUCKET: ${{ inputs.bucket-prefix }}-${{ secrets.aws-account-id }}-${{ inputs.aws-region }}-an
      PROJECT: ${{ inputs.project }}
      S3_KEY: ${{ inputs.s3-key-prefix }}.json
    steps:
      - name: Check Out Code
        uses: actions/checkout@v7
      - name: Minify JSON
        run: jq --compact-output '.lists |= map(select(.hidden != true))' "$PROJECT.json" > "$PROJECT.min.json"
      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@e6de054238d6b7531b4efff3b6587d9aade6a06c # v6.2.3
        with:
          role-to-assume: arn:aws:iam::${{ secrets.aws-account-id }}:role/${{ inputs.project }}.github-update
          role-session-name: github-upload
          aws-region: ${{ inputs.aws-region }}
      - name: Upload to S3
        run: aws s3 cp "$PROJECT.min.json" "s3://$AWS_BUCKET/$S3_KEY"
```

The concurrency group includes `project`, `aws-region`, and `s3-key-prefix` —
the inputs that identify the call — per `CLAUDE.md`, so two calls from one
caller cannot cancel each other.

### The callers

Each consumer's `.github/workflows/workflow.yml` becomes (BurgerList shown):

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
    permissions:            # REQUIRED — id-token is capped by the caller
      id-token: write
      contents: read
    uses: jluszcz/github-utils/.github/workflows/minify-and-upload.yml@v1
    with:
      aws-region: us-east-2
      project: burgerlist
      s3-key-prefix: burgerl.ist
      bucket-prefix: list-of-lists
    secrets:
      aws-account-id: ${{ secrets.AWS_ACCOUNT_ID }}
```

MovieList and StarList differ only in `paths`, `project`, and `s3-key-prefix`.

### Behavior changes

- The action versions move forward: `actions/checkout` v6 → v7, and
  `configure-aws-credentials` v6.0.0 (mutable tag) → the SHA pinned at v6.2.3.
- The job's status-check name becomes
  `minify-and-upload-to-s3 / Minify and Upload`. These workflows run on
  `push` to `main`, not on PRs, so no ruleset should require them — verify per
  repo with `gh api repos/jluszcz/<repo>/rulesets` before merging.
- `AWS_DEFAULT_REGION` is no longer read by these three repos. Leave the secret
  in place; removing it is out of scope.

### Verification

- `uv run pre-commit run --all-files` in `github-utils` (runs `actionlint`).
- All three repos are migrated in this effort. After each caller PR merges,
  confirm the resulting `Upload to S3` run succeeded and the object landed
  (`aws s3 ls s3://list-of-lists-<account>-us-east-2-an/`).

### Out of scope

- The stale committed `burgerlist.min.json` / `movielist.min.json` artifacts.
- Adding Dependabot to the three consumer repos.

## Stages

### Stage 1: Reusable workflow in `github-utils`
**Goal**: `.github/workflows/minify-and-upload.yml` plus a README caller section
and a `CHANGELOG.md` entry under `## v1 — 2026-08-01`.
**Success Criteria**: `uv run pre-commit run --all-files` passes (actionlint
parses the new workflow); README documents all four inputs and the secret.
**Tests**: `uv run pre-commit run --all-files`; `uv run pytest` (unchanged).
**Status**: In Progress — workflow, README, and CHANGELOG written; pre-commit
(10 hooks incl. actionlint) and `pytest` (18 passed) green.

### Stage 2: Release `v1`
**Goal**: After the Stage 1 PR merges, move the `v1` tag so callers resolve the
new workflow.
**Success Criteria**: `scripts/release.py --dry-run` previews the expected tag;
`v1` points at `origin/main`'s tip.
**Tests**: `gh api repos/jluszcz/github-utils/contents/.github/workflows/minify-and-upload.yml?ref=v1`
returns the file.
**Status**: Not Started

### Stage 3: Migrate the three callers
**Goal**: Replace `workflow.yml` in BurgerList, MovieList, and StarList with
thin callers. One branch + PR per repo.
**Success Criteria**: Each PR merges; the post-merge `Upload to S3` run
succeeds and the object lands in S3.
**Tests**: Confirm no ruleset requires the old check name
(`gh api repos/jluszcz/<repo>/rulesets`); watch each run with `gh run watch`.
**Status**: Not Started
