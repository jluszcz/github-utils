# Changelog

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
