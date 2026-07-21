# Shared CI Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the duplicated per-language CI logic across `jluszcz` repos into three reusable `workflow_call` workflows in `github-utils`, and migrate one exemplar consumer per language.

**Architecture:** Each reusable workflow defines a single job named `Build, Test & Lint`. Consumers replace their `ci.yml` body with a thin caller that keeps its own `on:`/`permissions` and delegates via `uses:` — the same pattern as the existing `claude.yml`/`auto-merge.yml`. Deployment is out of scope.

**Tech Stack:** GitHub Actions reusable workflows (YAML), `actionlint` + `shellcheck` for static validation, `gh` CLI for ruleset updates.

## Global Constraints

- These are config files, not application code: the per-task "test" is `actionlint` (with shellcheck) passing locally; the true integration test is a **green `ci / Build, Test & Lint` check** on a real consumer once the workflows are released. There are no unit tests.
- Reusable workflow files live at `github-utils/.github/workflows/<name>.yml` and are triggered by `on: workflow_call`.
- Every reusable workflow's job is named exactly `Build, Test & Lint`; every consumer's caller job key is exactly `ci`. Resulting required status check: `ci / Build, Test & Lint`.
- Pin action versions to those already used in this repo family: `actions/checkout@v7`, `actions/setup-node@v6`, `astral-sh/setup-uv@v8.3.0`, `actions/cache@v6`, `Swatinem/rust-cache@v2`.
- `permissions:` on each reusable workflow is `contents: read`.
- Never bypass hooks (`--no-verify`) or amend. Commit to feature branches only.
- Releasing `github-utils` changes: additive change → **move the `v1` tag** (per repo's `README.md` release policy), recorded in `CHANGELOG.md` in the same PR.

## File Structure

**github-utils (branch `shared-ci-workflows`, already checked out):**
- Create: `.github/workflows/rust-ci.yml` — reusable Rust CI (inputs: `runs-on`, `target`, `all-features`)
- Create: `.github/workflows/node-ci.yml` — reusable Node CI (input: `node-version`)
- Create: `.github/workflows/python-ci.yml` — reusable Python CI (no inputs)
- Modify: `README.md` — add a caller-doc section per new workflow
- Modify: `CHANGELOG.md` — add release entry

**Exemplar consumers (each its own repo / branch / PR):**
- Modify: `rust-utils/.github/workflows/ci.yml` — replace body with `rust-ci` caller
- Modify: `Seen/.github/workflows/ci.yml` — replace body with `node-ci` caller
- Modify: `plexport/.github/workflows/ci.yml` — replace body with `python-ci` caller
- Update each repo's `main` ruleset required-status-check context to `ci / Build, Test & Lint`

---

## Phase 1 — Reusable workflows in github-utils

All Phase 1 tasks are on the existing `shared-ci-workflows` branch. The exact
workflow contents below are already `actionlint`-validated (including
shellcheck).

### Task 1: Add `rust-ci.yml`

**Files:**
- Create: `github-utils/.github/workflows/rust-ci.yml`

**Interfaces:**
- Produces: reusable workflow `jluszcz/github-utils/.github/workflows/rust-ci.yml` with inputs `runs-on` (string, default `ubuntu-latest`), `target` (string, default `''`), `all-features` (boolean, default `false`); job named `Build, Test & Lint`.

- [ ] **Step 1: Create the file** with exactly this content:

```yaml
name: Rust CI

on:
  workflow_call:
    inputs:
      runs-on:
        description: Runner label to execute on
        type: string
        default: ubuntu-latest
      target:
        description: Rust target triple (e.g. aarch64-unknown-linux-musl); empty for native
        type: string
        default: ''
      all-features:
        description: Pass --all-features to build/test/lint
        type: boolean
        default: false

permissions:
  contents: read

jobs:
  build:
    name: Build, Test & Lint
    runs-on: ${{ inputs.runs-on }}

    env:
      TARGET_FLAG: ${{ inputs.target != '' && format('--target {0}', inputs.target) || '' }}
      FEATURES_FLAG: ${{ inputs.all-features && '--all-features' || '' }}

    steps:
      - uses: actions/checkout@v7

      - name: Update and Configure Rust
        env:
          TARGET: ${{ inputs.target }}
        run: |
          rustup update
          rustup component add clippy rustfmt
          if [ -n "$TARGET" ]; then
            sudo apt-get install -y musl-tools
            rustup target add "$TARGET"
          fi

      - name: Dump Toolchain Info
        run: |
          cargo --version --verbose
          rustc --version
          cargo clippy --version

      - name: Cache Cargo
        uses: Swatinem/rust-cache@v2

      - name: Build
        run: |
          # shellcheck disable=SC2086
          cargo build $TARGET_FLAG $FEATURES_FLAG

      - name: Test
        run: |
          # shellcheck disable=SC2086
          cargo test $TARGET_FLAG $FEATURES_FLAG

      - name: Format
        run: cargo fmt --check

      - name: Lint
        run: |
          # shellcheck disable=SC2086
          cargo clippy $TARGET_FLAG --all-targets $FEATURES_FLAG -- -D warnings
```

- [ ] **Step 2: Validate with actionlint (this is the test)**

Run: `cd github-utils && actionlint .github/workflows/rust-ci.yml`
Expected: no output, exit code 0 (PASS). Any shellcheck/syntax error is a failure — fix and re-run.

- [ ] **Step 3: Commit**

```bash
cd github-utils
git add .github/workflows/rust-ci.yml
git commit -m "feat: add reusable rust-ci workflow"
```

### Task 2: Add `node-ci.yml`

**Files:**
- Create: `github-utils/.github/workflows/node-ci.yml`

**Interfaces:**
- Produces: reusable workflow `jluszcz/github-utils/.github/workflows/node-ci.yml` with input `node-version` (string, default `'22'`); job named `Build, Test & Lint`. Always runs `npm run build`.

- [ ] **Step 1: Create the file** with exactly this content:

```yaml
name: Node CI

on:
  workflow_call:
    inputs:
      node-version:
        description: Node.js version for setup-node
        type: string
        default: '22'

permissions:
  contents: read

jobs:
  build:
    name: Build, Test & Lint
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v7

      - name: Setup Node.js
        uses: actions/setup-node@v6
        with:
          node-version: ${{ inputs.node-version }}
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Build
        run: npm run build

      - name: Test
        run: npm test

      - name: Lint
        run: |
          npm run lint
          npm run format:check
```

- [ ] **Step 2: Validate with actionlint**

Run: `cd github-utils && actionlint .github/workflows/node-ci.yml`
Expected: no output, exit code 0 (PASS).

- [ ] **Step 3: Commit**

```bash
cd github-utils
git add .github/workflows/node-ci.yml
git commit -m "feat: add reusable node-ci workflow"
```

### Task 3: Add `python-ci.yml`

**Files:**
- Create: `github-utils/.github/workflows/python-ci.yml`

**Interfaces:**
- Produces: reusable workflow `jluszcz/github-utils/.github/workflows/python-ci.yml` with no inputs; job named `Build, Test & Lint`.

- [ ] **Step 1: Create the file** with exactly this content:

```yaml
name: Python CI

on:
  workflow_call:

permissions:
  contents: read

jobs:
  build:
    name: Build, Test & Lint
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Install uv
        uses: astral-sh/setup-uv@v8.3.0

      - name: Install dependencies
        run: uv sync --locked

      - name: Cache pre-commit environments
        uses: actions/cache@v6
        with:
          path: ~/.cache/pre-commit
          key: pre-commit-${{ hashFiles('.pre-commit-config.yaml') }}
          restore-keys: |
            pre-commit-

      - name: Test
        run: uv run pytest

      - name: Lint
        run: uv run pre-commit run --all-files --show-diff-on-failure
```

- [ ] **Step 2: Validate with actionlint**

Run: `cd github-utils && actionlint .github/workflows/python-ci.yml`
Expected: no output, exit code 0 (PASS).

- [ ] **Step 3: Commit**

```bash
cd github-utils
git add .github/workflows/python-ci.yml
git commit -m "feat: add reusable python-ci workflow"
```

### Task 4: Document callers + CHANGELOG

**Files:**
- Modify: `github-utils/README.md`
- Modify: `github-utils/CHANGELOG.md`

**Interfaces:**
- Consumes: the three workflow filenames and input names from Tasks 1-3.

- [ ] **Step 1: Add three caller sections to `README.md`** under the `## Callers` section (after the existing `auto-merge.yml` subsection). Insert exactly:

````markdown
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

Consumers must define a `build` script in `package.json` (the workflow always
runs `npm run build`).

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

Consumers must use `uv` (with `uv.lock`) and a `.pre-commit-config.yaml`.
````

- [ ] **Step 2: Add a `CHANGELOG.md` entry** directly under the `# Changelog` heading, above the existing `## v1 — 2026-07-20` entry:

```markdown
## v1 — 2026-07-20 (CI workflows)

Added reusable `rust-ci.yml`, `node-ci.yml`, and `python-ci.yml`. Each defines a
single `Build, Test & Lint` job, extracted from the per-repo `ci.yml` copies.
`rust-ci` takes optional `runs-on`/`target`/`all-features` inputs; `node-ci`
takes optional `node-version` and always runs `npm run build`; `python-ci`
takes no inputs. Additive — no change to existing callers.
```

- [ ] **Step 3: Commit**

```bash
cd github-utils
git add README.md CHANGELOG.md
git commit -m "docs: document reusable CI workflow callers"
```

### Task 5: Release — open PR, merge, move `v1`

**Files:** none (git/release operations).

**Interfaces:**
- Produces: the `v1` tag pointing at a commit on `main` that contains the three new workflows, so exemplar callers pinned `@v1` resolve.

- [ ] **Step 1: Push the branch and open a PR**

```bash
cd github-utils
git push -u origin shared-ci-workflows
gh pr create --fill
```

- [ ] **Step 2: Confirm CI is green.** The repo's own `ci.yml` runs `actionlint` over `.github/workflows/**`, which now includes the three new files.

Run: `gh pr checks --watch`
Expected: `Lint Workflows` passes. (Auto-merge handles the merge once green; if it does not merge automatically, merge with `gh pr merge --squash`.)

- [ ] **Step 3: After the PR merges, move the `v1` tag**

```bash
cd github-utils
git checkout main && git pull
git tag -fa v1 -m "v1: add reusable rust-ci, node-ci, python-ci workflows"
git push --force origin v1
```

- [ ] **Step 4: Verify the tag points at the merge**

Run: `git log --oneline -1 v1`
Expected: the merge commit (or the squashed commit) that added the workflows.

---

## Phase 2 — Exemplar consumer migrations

**Ordering:** Phase 2 requires Task 5 complete — the callers reference `@v1`, and
their CI cannot go green until `v1` includes the new workflows. Each exemplar is
a separate repo with its own branch, PR, and ruleset update.

### Task 6: Migrate `rust-utils`

**Files:**
- Modify: `rust-utils/.github/workflows/ci.yml`
- Update: `rust-utils` `main` ruleset required check

**Interfaces:**
- Consumes: `rust-ci.yml@v1` with `runs-on`, `target`, `all-features` (from Task 1).

- [ ] **Step 1: Create a branch**

```bash
cd rust-utils
git switch -c shared-ci-workflow -t origin/main
```

- [ ] **Step 2: Replace `.github/workflows/ci.yml`** with exactly this content (the `on:`/`permissions` block is preserved verbatim from the current file; only the job body changes):

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
      all-features: true
```

- [ ] **Step 3: Validate with actionlint**

Run: `cd rust-utils && actionlint .github/workflows/ci.yml`
Expected: no output, exit code 0 (PASS).

- [ ] **Step 4: Commit and push**

```bash
cd rust-utils
git add .github/workflows/ci.yml
git commit -m "ci: use shared rust-ci reusable workflow"
git push -u origin shared-ci-workflow
gh pr create --fill
```

- [ ] **Step 5: Update the `main` ruleset required check** from `Build, Test & Lint` to `ci / Build, Test & Lint`.

```bash
cd rust-utils
RID=$(gh api repos/jluszcz/rust-utils/rulesets --jq '.[0].id')
gh api "repos/jluszcz/rust-utils/rulesets/$RID" \
  --jq '{name,target,enforcement,conditions,rules,bypass_actors}
        | (.rules[] | select(.type=="required_status_checks").parameters.required_status_checks[]
           | select(.context=="Build, Test & Lint").context) = "ci / Build, Test & Lint"' \
  > /tmp/rust-utils-ruleset.json
gh api -X PUT "repos/jluszcz/rust-utils/rulesets/$RID" --input /tmp/rust-utils-ruleset.json
```

- [ ] **Step 6: Verify the check ran green and the ruleset is updated**

Run: `gh pr checks --watch` (in `rust-utils`)
Expected: `ci / Build, Test & Lint` passes.
Run: `gh api "repos/jluszcz/rust-utils/rulesets/$RID" --jq '.rules[] | select(.type=="required_status_checks").parameters.required_status_checks[].context'`
Expected: includes `ci / Build, Test & Lint` (no bare `Build, Test & Lint`).

- [ ] **Step 7: Merge** once green (auto-merge should handle it; otherwise `gh pr merge --squash`).

### Task 7: Migrate `Seen`

**Files:**
- Modify: `Seen/.github/workflows/ci.yml`
- Update: `Seen` `main` ruleset required check

**Interfaces:**
- Consumes: `node-ci.yml@v1` (from Task 2). `Seen` already has a `build` script in `package.json` (verified), so no `package.json` change is needed.

- [ ] **Step 1: Create a branch**

```bash
cd Seen
git switch -c shared-ci-workflow -t origin/main
```

- [ ] **Step 2: Replace `.github/workflows/ci.yml`** with exactly this content (`on:`/`permissions` preserved from the current file):

```yaml
name: CI

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

permissions:
  contents: read

jobs:
  ci:
    uses: jluszcz/github-utils/.github/workflows/node-ci.yml@v1
```

- [ ] **Step 3: Validate with actionlint**

Run: `cd Seen && actionlint .github/workflows/ci.yml`
Expected: no output, exit code 0 (PASS).

- [ ] **Step 4: Commit and push**

```bash
cd Seen
git add .github/workflows/ci.yml
git commit -m "ci: use shared node-ci reusable workflow"
git push -u origin shared-ci-workflow
gh pr create --fill
```

- [ ] **Step 5: Update the `main` ruleset required check** from `Build, Test & Lint` to `ci / Build, Test & Lint`.

```bash
cd Seen
RID=$(gh api repos/jluszcz/Seen/rulesets --jq '.[0].id')
gh api "repos/jluszcz/Seen/rulesets/$RID" \
  --jq '{name,target,enforcement,conditions,rules,bypass_actors}
        | (.rules[] | select(.type=="required_status_checks").parameters.required_status_checks[]
           | select(.context=="Build, Test & Lint").context) = "ci / Build, Test & Lint"' \
  > /tmp/seen-ruleset.json
gh api -X PUT "repos/jluszcz/Seen/rulesets/$RID" --input /tmp/seen-ruleset.json
```

- [ ] **Step 6: Verify** as in Task 6, Step 6 (substituting `Seen`).

- [ ] **Step 7: Merge** once green.

### Task 8: Migrate `plexport`

**Files:**
- Modify: `plexport/.github/workflows/ci.yml`
- Update: `plexport` `main` ruleset required check

**Interfaces:**
- Consumes: `python-ci.yml@v1` (from Task 3).

- [ ] **Step 1: Create a branch**

```bash
cd plexport
git switch -c shared-ci-workflow -t origin/main
```

- [ ] **Step 2: Replace `.github/workflows/ci.yml`** with exactly this content (`on:`/`permissions` preserved from the current file):

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

- [ ] **Step 3: Validate with actionlint**

Run: `cd plexport && actionlint .github/workflows/ci.yml`
Expected: no output, exit code 0 (PASS).

- [ ] **Step 4: Commit and push**

```bash
cd plexport
git add .github/workflows/ci.yml
git commit -m "ci: use shared python-ci reusable workflow"
git push -u origin shared-ci-workflow
gh pr create --fill
```

- [ ] **Step 5: Update the `main` ruleset required check** from `Build, Test & Lint` to `ci / Build, Test & Lint`. First confirm the current context string (plexport's job is named `Test & Lint`, not `Build, Test & Lint` — verify before editing):

```bash
cd plexport
RID=$(gh api repos/jluszcz/plexport/rulesets --jq '.[0].id')
gh api "repos/jluszcz/plexport/rulesets/$RID" \
  --jq '.rules[] | select(.type=="required_status_checks").parameters.required_status_checks[].context'
```

Then replace whichever bare context string it reports (e.g. `Test & Lint`) with `ci / Build, Test & Lint`:

```bash
OLD="Test & Lint"   # set to the exact string printed above
gh api "repos/jluszcz/plexport/rulesets/$RID" \
  --jq --arg old "$OLD" '{name,target,enforcement,conditions,rules,bypass_actors}
        | (.rules[] | select(.type=="required_status_checks").parameters.required_status_checks[]
           | select(.context==$old).context) = "ci / Build, Test & Lint"' \
  > /tmp/plexport-ruleset.json
gh api -X PUT "repos/jluszcz/plexport/rulesets/$RID" --input /tmp/plexport-ruleset.json
```

- [ ] **Step 6: Verify** as in Task 6, Step 6 (substituting `plexport`).

- [ ] **Step 7: Merge** once green.

---

## Deferred to a documented follow-up (not in this plan)

- The remaining ~12 consumer migrations: native Rust (`AdventOfCode-rs`, `Renamer`, `todoer`), remaining Node (`Elonulator`, `EndTimes`, `LottoCheck`, `Outwatch`), and the 6 musl/Lambda repos.
- The Lambda `package`-split restructuring (see the design spec's "Lambda-repo restructuring" section) — the primary residual risk, not exercised by the exemplars.
- Adding a `build` script to `EndTimes` and `LottoCheck` `package.json`.
- All deployment workflows.
