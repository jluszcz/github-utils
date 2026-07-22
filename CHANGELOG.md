# Changelog

## v1 — 2026-07-22 (Hardening + concurrency)

Pinned all third-party actions to commit SHAs (`Swatinem/rust-cache`,
`raven-actions/actionlint`, `astral-sh/setup-uv`, `aws-actions/configure-aws-credentials`,
`anthropics/claude-code-action`); first-party `actions/*` stay on major tags.
Added `concurrency` (cancel superseded runs, latest wins) to `rust-ci`,
`node-ci`, `python-ci`, `lambda-package`, and `deploy-lambda`. `python-ci` now
enables the uv cache. Rust toolchain setup runs
`apt-get update` before installing `musl-tools`, and `lambda-package` reorders
`rustup update` before `rustup target add` to match `rust-ci`. Additive — no
change to caller inputs or job names.

## v1 — 2026-07-21 (Lambda package + deploy)

Added reusable `lambda-package.yml` (release build + zip + upload) and
`deploy-lambda.yml` (OIDC assume-role + `s3 cp`). Deploy role standardized to
`${project}.github-deploy` with an optional `.${region}` suffix (`regional`
input). Additive — no change to existing callers.

## v1 — 2026-07-20 (CI workflows)

Added reusable `rust-ci.yml`, `node-ci.yml`, and `python-ci.yml`. Each defines a
single `Build, Test & Lint` job, extracted from the per-repo `ci.yml` copies.
`rust-ci` takes optional `runs-on`/`target`/`all-features` inputs; `node-ci`
takes optional `node-version` and always runs `npm run build`; `python-ci`
takes no inputs. Additive — no change to existing callers.

## v1 — 2026-07-20

Initial release. Reusable `claude.yml`, `claude-code-review.yml`, and
`auto-merge.yml`, extracted verbatim from the per-repo copies (no behavior
change). `auto-merge.yml` uses the broad Dependabot-or-`Deps-*` logic.
