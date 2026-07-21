# Python CI (dogfood `python-ci.yml`) design

**Date:** 2026-07-21
**Status:** Approved

## Problem

The repo now ships real Python (`scripts/release.py` + `scripts/test_release.py`)
but nothing tests it in CI. The repo also *defines* the reusable
`python-ci.yml` workflow. Rather than write a one-off test job, dogfood the
reusable workflow against this repo's own script — validating the workflow and
testing the script at once.

## Approach

Add the `uv` + `pytest` + `pre-commit` stack the reusable `python-ci.yml`
expects (`uv sync --locked`, `uv run pytest`, `uv run pre-commit run
--all-files`), modeled on the `plexport` consumer, then call the reusable
workflow from this repo's `ci.yml` via a **local `./` ref** so CI validates the
in-repo version.

## Files

- **Create `pyproject.toml`:**
  - `[project]` name `github-utils`, `version = "0.0.0"`, `requires-python =
    ">=3.11"`, no runtime `dependencies`.
  - `[dependency-groups] dev = ["pre-commit>=4", "pytest>=8"]`.
  - `[tool.ruff.lint] select = ["E", "F", "I", "UP", "B", "SIM"]`.
  - `[tool.ruff.lint.isort] known-first-party = ["release"]` (the test imports
    `from release import ...`).
  - `[tool.pytest.ini_options] testpaths = ["scripts"]` (tests live in
    `scripts/`, not `tests/`).
  - No extensionless-file ruff overrides — this repo's Python is normal `.py`.
- **Create `.pre-commit-config.yaml`:** `pre-commit/pre-commit-hooks` v5
  (check-merge-conflict, check-toml, check-yaml, detect-aws-credentials
  `--allow-missing-credentials`, end-of-file-fixer, file-contents-sorter on
  `.gitignore`, trailing-whitespace) + `astral-sh/ruff-pre-commit` (`ruff-check
  --fix`, `ruff-format`) with default file matching (no extensionless
  overrides). Pin the same `rev`s `plexport` uses.
- **Generate `uv.lock`:** via `uv lock`.
- **Modify `.github/workflows/ci.yml`:** add a second job alongside the existing
  `Lint Workflows` actionlint job:
  ```yaml
    python:
      name: Python
      uses: ./.github/workflows/python-ci.yml
  ```
- **Modify `.gitignore`:** add `.venv/`, `.ruff_cache/`, `.pytest_cache/` (keep
  it sorted — `file-contents-sorter` runs on it).
- **Modify `README.md`:** one note that the repo dogfoods `python-ci.yml` on
  `scripts/`.

## Constraints

- The reusable workflow and its `on: workflow_call` contract are unchanged.
- Triggers on `ci.yml` are unchanged: `pull_request` (no path filter) already
  runs both jobs on every PR; the merge of this PR touches
  `.github/workflows/**` so the push-to-main run fires too.
- `pre-commit run --all-files` may reformat existing `scripts/*.py` (ruff-format)
  and adjust whitespace/EOF on existing files. Let it, and commit the result so
  CI is green.

## Verification (local, before pushing)

1. `uv lock` then `uv sync --locked` — succeeds, lockfile committed.
2. `uv run pytest` — 12 tests pass.
3. `uv run pre-commit run --all-files` — all hooks pass (after committing any
   reformat the first run applies).
4. `actionlint` clean on the edited `ci.yml` (the repo's own `Lint Workflows`).
