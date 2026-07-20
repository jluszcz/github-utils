# Shared Source of Truth: `jluszcz/github-utils` Reusable Workflows

**Date:** 2026-07-20
**Status:** Design approved
**Origin:** Improvement #5 of `workflow-review.md` (GitHub Workflows Consistency Review, 2026-07-19)

## Problem

Ten-plus public repos under the `jluszcz` user account hand-copy `claude.yml`,
`claude-code-review.yml`, and `auto-merge.yml`. The copies have drifted
independently (whitespace variants, one functional straggler in
`claude-code-review.yml`, a narrower auto-merge in the JS/Python repos). Every
version bump or condition fix must currently be applied by hand in every repo.

## Goal

Move the shared logic into one place so a fix or version bump happens once and
propagates. Each consuming repo shrinks to a thin caller of ~10–15 lines.

## Non-goals (explicitly out of scope)

- `deploy-lambda.yml` — already reusable but Rust/Lambda-specific (needs region,
  project, and IAM-role parameterization). Deferred.
- `ci.yml` — too per-project (14 distinct variants) to centralize usefully now.

## Constraints & context

- All consuming repos are **public** and owned by the **user** account `jluszcz`
  (no organization). Cross-repo reusable-workflow references therefore "just
  work"; org-only features (required workflows, org default files) are not
  available and not needed.
- `claude.yml`, `claude-code-review.yml`, and `auto-merge.yml` are all
  **event-triggered** (`issue_comment`, `pull_request`, `pull_request_review`,
  etc.). A reusable workflow (`workflow_call`) cannot listen to events directly,
  so each repo keeps a thin caller that owns the `on:` triggers.

## Design

### 1. The shared repo: `jluszcz/github-utils`

A new public repo. Reusable workflows live at `.github/workflows/` (GitHub
requires reusable workflows to be under that path regardless of repo name):

- `.github/workflows/claude.yml` — `on: workflow_call`; body is the
  `@claude`-mention job.
- `.github/workflows/claude-code-review.yml` — `on: workflow_call`; body is the
  PR-review job including the dependency-PR skip.
- `.github/workflows/auto-merge.yml` — `on: workflow_call`; body enables
  auto-merge with the broad Dependabot-or-`Deps-*` logic.

The `if` gates (mention detection, dependency-PR skip, auto-merge conditions)
**stay inside the reusable workflows**. Inside a reusable workflow,
`github.event` and `github.event_name` refer to the caller's *originating*
event, so the existing conditions work unchanged and callers stay minimal.

Each reusable job declares its own `permissions`. Secrets are received via the
caller's `secrets: inherit`.

### 2. Per-repo thin callers

Each repo keeps a file with the **same filename** as today (so triggers,
branch-protection wiring, and habits don't change), reduced to triggers plus one
`uses:`. Example `claude.yml`:

```yaml
name: Claude Code
on:
  issue_comment: { types: [created] }
  pull_request_review_comment: { types: [created] }
  issues: { types: [opened, assigned] }
  pull_request_review: { types: [submitted] }
jobs:
  claude:
    uses: jluszcz/github-utils/.github/workflows/claude.yml@v1
    secrets: inherit
```

`claude-code-review.yml` and `auto-merge.yml` callers follow the same shape with
their own `on:` triggers.

### 3. Versioning

- Callers pin `@v1` (a **moving major tag**).
- **Patch/minor** fixes: move the `v1` tag → propagate silently on next run
  (fix-once preserved, no per-repo PRs).
- **Breaking** changes: cut `v2`. Each repo's Dependabot `github-actions`
  ecosystem tracks the reusable-workflow `uses:` ref and opens reviewable
  `@v1`→`@v2` bump PRs.
- A `CHANGELOG.md` in `github-utils` records each tag move and what changed.

### 4. Auto-merge unification

The JS/Python repos (Elonulator, EndTimes, LottoCheck, Outwatch, plexport, Seen)
currently have a narrower `dependabot-auto-merge.yml` (Dependabot only). On
migration that file is **deleted** and replaced by an `auto-merge.yml` caller, so
every repo converges on the broad logic: auto-merge Dependabot PRs **or**
`jluszcz` PRs from `Deps-*` branches.

## Key risk: status-check renaming

Moving a job into a reusable workflow **changes its status-check name**: the
check `claude-review` becomes `<caller-job> / claude-review`. In any repo where
`claude-review` (or an auto-merge check) is a **required check** in branch
protection, the required check will sit permanently "pending" until the branch
protection rule is updated to the new name.

**Mitigation:** before flipping any repo, audit its branch-protection required
checks and update renamed check names as part of that repo's migration.

## Rollout (canary-first)

1. Create `jluszcz/github-utils`; add the three reusable workflows; lint with
   `actionlint`; tag `v1`.
2. **Canary one low-stakes repo** (e.g. `rust-utils`) with callers pinned to
   `@v1` (optionally a branch ref first). Verify all three fire against real
   events: a `@claude` comment, a dependency PR, and a normal PR review.
3. Audit and fix branch-protection required-check names on the canary.
4. Roll out to the remaining repos: replace full workflow bodies with callers;
   delete `dependabot-auto-merge.yml` where present; audit required checks per
   repo.

## Testing strategy

Reusable workflows can't be meaningfully unit-tested (`act` support is
unreliable). Validation is:

- `actionlint` on the reusable workflows and callers (static/YAML checks).
- The canary repo exercising each workflow against real triggering events before
  wider rollout.

## Consuming repos (reference)

- **claude.yml / claude-code-review.yml:** all 17 repos with a `.github`
  directory.
- **auto-merge.yml (broad, already):** AdventOfCode-rs, JakeSky-rs, LambdUpdate,
  ListOfLists-rs, LogStreamGC, mbtalerts, rust-utils.
- **auto-merge.yml (migrate from `dependabot-auto-merge.yml`):** Elonulator,
  EndTimes, LottoCheck, Outwatch, plexport, Seen.
- **No auto-merge today (add during rollout, as desired):** Renamer, todoer,
  jluszcz.com, skills.
