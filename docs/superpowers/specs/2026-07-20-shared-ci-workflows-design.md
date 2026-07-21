# Shared CI Workflows

## Goal

Uplift the duplicated per-language CI logic scattered across the `jluszcz`
repositories into reusable `workflow_call` workflows in `github-utils`, so CI is
fixed once here and every consumer picks it up on its next run — the same model
already used for `claude.yml`, `claude-code-review.yml`, and `auto-merge.yml`.

Deployment workflows (Lambda packaging, S3 upload, `deploy-lambda.yml`,
`minify-and-upload-to-s3.yml`) are explicitly **out of scope** and deferred to a
separate change.

## Survey (why these three workflows)

Sixteen sibling repos have a `ci.yml`. They fall into three near-identical
language groups:

- **Rust (9):** `AdventOfCode-rs`, `JakeSky-rs`, `LambdUpdate`, `ListOfLists-rs`,
  `LogStreamGC`, `mbtalerts`, `Renamer`, `rust-utils`, `todoer`. Every one runs
  the same job: `rustup update` + add `clippy`/`rustfmt`, dump toolchain info,
  `Swatinem/rust-cache@v2`, then `cargo build` / `cargo test` /
  `cargo fmt --check` / `cargo clippy --all-targets -- -D warnings`.
- **Node (5):** `Elonulator`, `EndTimes`, `LottoCheck`, `Outwatch`, `Seen`.
  Identical: `actions/setup-node@v6` (node 22, npm cache) → `npm ci` →
  (`npm run build`) → `npm test` → `npm run lint` + `npm run format:check`.
- **Python (1):** `plexport`. `astral-sh/setup-uv` → `uv sync --locked` →
  cache pre-commit → `uv run pytest` → `uv run pre-commit run --all-files`.

The variation within each group is small and parameterizable (see inputs below).

## Architecture

Three new reusable workflows under `github-utils/.github/workflows/`, each
defining a single job named **`Build, Test & Lint`** and triggered by
`workflow_call`. Consumers replace their `ci.yml` body with a thin caller that
keeps its own `on:` triggers / path filters and `permissions:`, and delegates
the job — matching the existing shared-workflow pattern.

### `rust-ci.yml`

| Input | Type | Default | Purpose |
|---|---|---|---|
| `runs-on` | string | `ubuntu-latest` | musl repos pass `ubuntu-24.04-arm` |
| `target` | string | `''` | when non-empty → `sudo apt-get install -y musl-tools`, `rustup target add <target>`, and `--target <target>` on build/test/clippy |
| `all-features` | boolean | `false` | when `true` → append `--all-features` to build/test/clippy |

Job steps (the shared sequence, verbatim, with `target`/`all-features` applied
conditionally):

1. `actions/checkout@v7`
2. Update & configure Rust: `rustup update`, `rustup component add clippy rustfmt`; if `target` set: install `musl-tools` and `rustup target add <target>`
3. Dump toolchain info (`cargo`/`rustc`/`clippy` versions)
4. `Swatinem/rust-cache@v2`
5. `cargo build [--target T] [--all-features]`
6. `cargo test [--target T] [--all-features]`
7. `cargo fmt --check`
8. `cargo clippy [--target T] --all-targets [--all-features] -- -D warnings`

Consumer mapping:

- Native (`AdventOfCode-rs`, `Renamer`, `todoer`): all defaults.
- musl (`JakeSky-rs`, `LambdUpdate`, `ListOfLists-rs`, `LogStreamGC`,
  `mbtalerts`): `runs-on: ubuntu-24.04-arm`, `target: aarch64-unknown-linux-musl`.
- `rust-utils`: above + `all-features: true`.

### `node-ci.yml`

| Input | Type | Default | Purpose |
|---|---|---|---|
| `node-version` | string | `'22'` | Node version for `setup-node` |

Job steps: `actions/checkout@v7` → `actions/setup-node@v6` (`cache: npm`) →
`npm ci` → `npm run build` → `npm test` → `npm run lint` → `npm run format:check`.

Decision: **always run `npm run build`.** `EndTimes` and `LottoCheck` currently
have no `build` script; a `build` script must be added to their `package.json`
during their migration.

### `python-ci.yml`

No inputs. Job steps mirror `plexport` exactly: `actions/checkout@v7` →
`astral-sh/setup-uv@v8.3.0` → `uv sync --locked` → cache `~/.cache/pre-commit`
keyed on `.pre-commit-config.yaml` → `uv run pytest` →
`uv run pre-commit run --all-files --show-diff-on-failure`.

## Lambda-repo restructuring (approach for the deferred bulk migration)

The 6 musl repos pack `Package`/`Upload` steps **inside** the `build` job, and
their `deploy` jobs `needs: build`. A job cannot both call a reusable workflow
and run steps, so migrating build/test/lint requires relocating packaging into
its own job. The deploy jobs stay byte-for-byte identical — only their `needs:`
is rewired.

```yaml
jobs:
  ci:
    uses: jluszcz/github-utils/.github/workflows/rust-ci.yml@v1
    with:
      runs-on: ubuntu-24.04-arm
      target: aarch64-unknown-linux-musl
  package:            # the old Package/Upload steps, now standalone
    needs: ci
    if: github.event_name == 'push'
    runs-on: ubuntu-24.04-arm
    steps: [checkout, install musl+target, cargo build --release --target, zip, upload-artifact]
  deploy...:          # unchanged; needs: package
```

**Known tradeoff / follow-up:** the standalone `package` job re-runs toolchain
setup + a release build in a fresh runner instead of piggybacking the build
job's warm state. `rust-cache` keeps the delta small. A later deployment change
can optimize this (e.g., have `rust-ci` output the built artifact). Not solved
here.

`rust-utils` has no packaging and migrates as a pure `ci:` caller.

## Status checks and rulesets

Required-status-check names live in each repo's ruleset (not classic branch
protection). Today the required check is the `build` job's name,
`Build, Test & Lint`. Calling a reusable workflow renames the check to
`<caller-job> / <reusable-job>`.

Standardize the caller job key as **`ci`** and keep the reusable job named
**`Build, Test & Lint`**, so every migrated repo's required check becomes the
single consistent string **`ci / Build, Test & Lint`**. Each migrated repo's
ruleset required-check must be updated to this string via
`gh api repos/jluszcz/<repo>/rulesets/<id>` (PUT back only
`name,target,enforcement,conditions,rules,bypass_actors`).

## Scope of this change

1. **github-utils:** add `rust-ci.yml`, `node-ci.yml`, `python-ci.yml`; document
   each caller in `README.md`; add a `CHANGELOG.md` entry; move the `v1` tag
   (additive → `v1` move, per the repo's release policy).
2. **Exemplar migrations (one per language)** to de-risk the pattern end-to-end,
   including ruleset updates:
   - **Rust → `rust-utils`** (exercises `target` + `all-features`, no
     deployment entanglement).
   - **Node → `Seen`** (already has a `build` script — no `package.json` change).
   - **Python → `plexport`**.

Each exemplar: replace `ci.yml` with the thin caller (preserving its existing
`on:`/`permissions`), confirm CI passes green, update the ruleset required-check
name to `ci / Build, Test & Lint`.

## Deferred to a documented follow-up

- The remaining ~12 consumer migrations (native Rust, remaining Node, and the 6
  Lambda repos using the restructuring above).
- Adding `build` scripts to `EndTimes` and `LottoCheck`.
- The exemplars intentionally do **not** exercise the Lambda `package`-split
  shape (Section "Lambda-repo restructuring") — that is the primary residual
  risk carried into the bulk migration.
- All deployment workflows.

## Success criteria

- `rust-ci.yml`, `node-ci.yml`, `python-ci.yml` exist in `github-utils`, pass
  `actionlint` (the repo's own required check), and are documented in `README.md`
  with a `CHANGELOG.md` entry.
- `rust-utils`, `Seen`, and `plexport` each run CI via the reusable workflow with
  a green `ci / Build, Test & Lint` check, and their rulesets require that check.
- No deployment behavior changes anywhere.
