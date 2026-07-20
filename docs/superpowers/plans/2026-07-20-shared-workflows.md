# Shared Workflows (`jluszcz/github-utils`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize `claude.yml`, `claude-code-review.yml`, and `auto-merge.yml` into reusable workflows in a new `jluszcz/github-utils` repo, and migrate every consuming repo to a thin caller so future fixes happen once.

**Architecture:** Three `on: workflow_call` reusable workflows hold the job bodies (the `if` gates stay inside them, since `github.event`/`github.event_name` in a reusable workflow reflect the caller's originating event). Each repo keeps a same-named file reduced to `on:` triggers plus a single `uses: jluszcz/github-utils/.github/workflows/<name>.yml@v1` with `secrets: inherit`. Callers pin the moving major tag `@v1`.

**Tech Stack:** GitHub Actions (reusable workflows / `workflow_call`), `gh` CLI, `actionlint` for static validation.

## Global Constraints

- Reusable workflows MUST live at `.github/workflows/` inside `github-utils` (GitHub requirement), even though the repo is not named `.github`.
- Caller reference is exactly `jluszcz/github-utils/.github/workflows/<name>.yml@v1`.
- `v1` is a **moving major tag**: patch/minor = move `v1`; breaking = cut `v2`.
- Callers keep the **same filename** as the workflow they replace (`claude.yml`, `claude-code-review.yml`, `auto-merge.yml`).
- Callers use `secrets: inherit`.
- **v1 preserves current behavior byte-for-behavior** — do NOT bump action versions (`checkout@v4`, `claude-code-action@v1`, etc.) in this plan. Action-version bumps are a deliberate follow-up `v1` tag-move (the first demonstration of fix-once), out of scope here.
- All consuming repos are public, owned by user `jluszcz`.
- **Status-check rename risk:** moving a job into a reusable workflow renames its check from `<job>` to `<caller-job> / <job>`. Every rollout task must audit branch-protection required checks for that repo before merging.

---

## Task 1: Create the three reusable workflows in `github-utils`

**Files:**
- Create: `github-utils/.github/workflows/claude.yml`
- Create: `github-utils/.github/workflows/claude-code-review.yml`
- Create: `github-utils/.github/workflows/auto-merge.yml`
- Create: `github-utils/README.md`
- Create: `github-utils/CHANGELOG.md`

**Interfaces:**
- Produces: three reusable workflows callable as `jluszcz/github-utils/.github/workflows/{claude,claude-code-review,auto-merge}.yml`, each with job ids `claude`, `claude-review`, `auto-merge` respectively.

- [ ] **Step 1: Write `.github/workflows/claude.yml`**

```yaml
name: Claude Code

on:
  workflow_call:

jobs:
  claude:
    if: |
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@claude')) ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@claude')) ||
      (github.event_name == 'pull_request_review' && contains(github.event.review.body, '@claude')) ||
      (github.event_name == 'issues' && (contains(github.event.issue.body, '@claude') || contains(github.event.issue.title, '@claude')))
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: read
      issues: read
      id-token: write
      actions: read # Required for Claude to read CI results on PRs
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Run Claude Code
        id: claude
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          additional_permissions: |
            actions: read
```

- [ ] **Step 2: Write `.github/workflows/claude-code-review.yml`**

```yaml
name: Claude Code Review

on:
  workflow_call:

jobs:
  claude-review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: read
      id-token: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Run Claude Code Review
        id: claude-review
        # Skip dependency PRs; job still reports success so the required check passes
        if: >
          github.event.pull_request.user.login != 'dependabot[bot]' &&
          !(github.event.pull_request.user.login == 'jluszcz' && startsWith(github.event.pull_request.head.ref, 'Deps-'))
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          allowed_bots: 'claude'
          track_progress: true
          plugin_marketplaces: 'https://github.com/anthropics/claude-code.git'
          plugins: 'code-review@claude-code-plugins'
          prompt: '/code-review:code-review ${{ github.repository }}/pull/${{ github.event.pull_request.number }} --comment'
          claude_args: |
            --allowedTools "mcp__github_inline_comment__create_inline_comment,Bash(gh issue view:*),Bash(gh search:*),Bash(gh issue list:*),Bash(gh pr comment:*),Bash(gh pr diff:*),Bash(gh pr view:*),Bash(gh pr list:*),Bash(git blame:*),Bash(git log:*),Bash(git show:*),Bash(git diff:*)"
```

- [ ] **Step 3: Write `.github/workflows/auto-merge.yml`**

```yaml
name: Auto-Merge

on:
  workflow_call:

jobs:
  auto-merge:
    runs-on: ubuntu-latest
    if: >
      github.event.pull_request.user.login == 'dependabot[bot]' ||
      (github.event.pull_request.user.login == 'jluszcz' && startsWith(github.event.pull_request.head.ref, 'Deps-'))

    permissions:
      contents: write
      pull-requests: write

    steps:
      - name: Enable auto-merge
        run: gh pr merge --auto --squash "$PR_URL"
        env:
          PR_URL: ${{ github.event.pull_request.html_url }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 4: Write `README.md` with copy-paste caller snippets**

````markdown
# github-utils

Reusable GitHub Actions workflows shared across `jluszcz` repositories. Fix once here; every consumer picks it up on its next run.

Consumers pin the moving major tag `@v1`. Patch/minor fixes move `v1`; breaking changes are cut as `v2` (Dependabot opens `@v1`→`@v2` PRs).

## Callers

### `.github/workflows/claude.yml`

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

### `.github/workflows/claude-code-review.yml`

```yaml
name: Claude Code Review
on:
  pull_request:
    types: [opened, synchronize, ready_for_review, reopened]
jobs:
  claude-review:
    uses: jluszcz/github-utils/.github/workflows/claude-code-review.yml@v1
    secrets: inherit
```

### `.github/workflows/auto-merge.yml`

```yaml
name: Auto-Merge
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  auto-merge:
    uses: jluszcz/github-utils/.github/workflows/auto-merge.yml@v1
    secrets: inherit
```
````

- [ ] **Step 5: Write `CHANGELOG.md`**

```markdown
# Changelog

## v1 — 2026-07-20

Initial release. Reusable `claude.yml`, `claude-code-review.yml`, and
`auto-merge.yml`, extracted verbatim from the per-repo copies (no behavior
change). `auto-merge.yml` uses the broad Dependabot-or-`Deps-*` logic.
```

- [ ] **Step 6: Validate all three workflows with actionlint**

Run:
```bash
cd /Users/jacob/Documents/Programs/github-utils
command -v actionlint >/dev/null 2>&1 || brew install actionlint
actionlint .github/workflows/*.yml
```
Expected: no output, exit code 0. (actionlint understands `workflow_call` and reports syntax/expression errors.)

- [ ] **Step 7: Commit**

```bash
cd /Users/jacob/Documents/Programs/github-utils
git add .github README.md CHANGELOG.md
git commit -m "feat: add reusable claude, claude-code-review, and auto-merge workflows"
```

---

## Task 2: Publish `github-utils` to GitHub and tag `v1`

**Files:** none (repo/tag operations only)

**Interfaces:**
- Consumes: the committed workflows from Task 1.
- Produces: `jluszcz/github-utils` public repo with a `v1` tag that callers can reference.

- [ ] **Step 1: Confirm `gh` is authenticated**

Run: `gh auth status`
Expected: logged in as `jluszcz`.

- [ ] **Step 2: Create the remote repo and push `main`**

Run:
```bash
cd /Users/jacob/Documents/Programs/github-utils
gh repo create jluszcz/github-utils --public --source=. --remote=origin --push
```
Expected: repo created; `main` pushed. (If the branch is not yet named `main`, run `git branch -M main` first.)

- [ ] **Step 3: Create and push the `v1` tag**

Run:
```bash
cd /Users/jacob/Documents/Programs/github-utils
git tag -a v1 -m "v1: initial reusable workflows"
git push origin v1
```

- [ ] **Step 4: Verify the tag resolves on GitHub**

Run: `gh api repos/jluszcz/github-utils/git/refs/tags/v1 --jq .ref`
Expected: `refs/tags/v1`

---

## Task 3: Canary — migrate `rust-utils` and verify live

`rust-utils` is a low-stakes library repo that already has the broad `auto-merge.yml`, so all three callers apply cleanly. This task proves the mechanism against real events before any other repo changes.

**Files:**
- Modify (replace whole body): `rust-utils/.github/workflows/claude.yml`
- Modify (replace whole body): `rust-utils/.github/workflows/claude-code-review.yml`
- Modify (replace whole body): `rust-utils/.github/workflows/auto-merge.yml`

**Interfaces:**
- Consumes: `v1` tag from Task 2.

- [ ] **Step 1: Create a migration branch**

Run:
```bash
cd /Users/jacob/Documents/Programs/rust-utils
git switch -c shared-workflows -t origin/main
```

- [ ] **Step 2: Replace `claude.yml` with the caller**

Overwrite `rust-utils/.github/workflows/claude.yml` with exactly:
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

- [ ] **Step 3: Replace `claude-code-review.yml` with the caller**

Overwrite `rust-utils/.github/workflows/claude-code-review.yml` with exactly:
```yaml
name: Claude Code Review
on:
  pull_request:
    types: [opened, synchronize, ready_for_review, reopened]
jobs:
  claude-review:
    uses: jluszcz/github-utils/.github/workflows/claude-code-review.yml@v1
    secrets: inherit
```

- [ ] **Step 4: Replace `auto-merge.yml` with the caller**

Overwrite `rust-utils/.github/workflows/auto-merge.yml` with exactly:
```yaml
name: Auto-Merge
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  auto-merge:
    uses: jluszcz/github-utils/.github/workflows/auto-merge.yml@v1
    secrets: inherit
```

- [ ] **Step 5: Validate the callers with actionlint**

Run:
```bash
cd /Users/jacob/Documents/Programs/rust-utils
actionlint .github/workflows/claude.yml .github/workflows/claude-code-review.yml .github/workflows/auto-merge.yml
```
Expected: no output, exit code 0.

- [ ] **Step 6: Commit and push the branch, open a PR**

Run:
```bash
cd /Users/jacob/Documents/Programs/rust-utils
git add .github/workflows/claude.yml .github/workflows/claude-code-review.yml .github/workflows/auto-merge.yml
git commit -m "refactor: use shared github-utils reusable workflows"
git push -u origin shared-workflows
gh pr create --fill --title "Use shared github-utils reusable workflows"
```

- [ ] **Step 7: Verify claude-code-review fires on the PR**

On the PR created in Step 6, confirm in the Actions tab that a check named `claude-review / claude-review` runs and succeeds (the review posts a comment, since this is not a dependency PR).
Run: `gh pr checks --watch`
Expected: the `claude-review / claude-review` check is present and green.

- [ ] **Step 8: Verify the `@claude` mention path**

Comment `@claude say hello` on the PR. Confirm the `Claude Code` workflow triggers and Claude responds.
Run: `gh run list --workflow=claude.yml --limit 3`
Expected: a run appears for the comment event.

- [ ] **Step 9: Audit branch-protection required checks**

Run: `gh api repos/jluszcz/rust-utils/branches/main/protection --jq '.required_status_checks.checks[]?.context' 2>/dev/null || echo "no branch protection / no required checks"`
If any required check is the old bare name (e.g. `claude-review`), update the rule to the new `claude-review / claude-review` name in the GitHub UI (Settings → Branches) before merging. Otherwise nothing to do.

- [ ] **Step 10: Merge the canary PR**

Run:
```bash
cd /Users/jacob/Documents/Programs/rust-utils
gh pr merge --squash --delete-branch
```
Expected: merged. `rust-utils` now runs entirely off the shared workflows.

---

## Task 4: Roll out to the remaining broad-auto-merge repos

These already have the broad `auto-merge.yml`, so all three callers apply identically to the canary: **AdventOfCode-rs, JakeSky-rs, LambdUpdate, ListOfLists-rs, LogStreamGC, mbtalerts.**

**Files (per repo):**
- Modify (replace whole body): `<repo>/.github/workflows/claude.yml`
- Modify (replace whole body): `<repo>/.github/workflows/claude-code-review.yml`
- Modify (replace whole body): `<repo>/.github/workflows/auto-merge.yml`

- [ ] **Step 1: Confirm each repo has all three source files**

Run:
```bash
cd /Users/jacob/Documents/Programs
for r in AdventOfCode-rs JakeSky-rs LambdUpdate ListOfLists-rs LogStreamGC mbtalerts; do
  echo "== $r =="
  ls "$r/.github/workflows/claude.yml" "$r/.github/workflows/claude-code-review.yml" "$r/.github/workflows/auto-merge.yml" 2>&1
done
```
Expected: all three files listed for each repo. Note any repo missing a file and skip that specific caller for it.

- [ ] **Step 2: For each repo, branch, replace the three files with the callers, validate, PR**

For each `<repo>` in the list, run (the three caller bodies are exactly those in Task 3 Steps 2–4):
```bash
cd /Users/jacob/Documents/Programs/<repo>
git switch -c shared-workflows -t origin/main
# overwrite the three .github/workflows/{claude,claude-code-review,auto-merge}.yml files
# with the Task 3 caller bodies (identical across repos)
actionlint .github/workflows/claude.yml .github/workflows/claude-code-review.yml .github/workflows/auto-merge.yml
git add .github/workflows/claude.yml .github/workflows/claude-code-review.yml .github/workflows/auto-merge.yml
git commit -m "refactor: use shared github-utils reusable workflows"
git push -u origin shared-workflows
gh pr create --fill --title "Use shared github-utils reusable workflows"
```
Expected per repo: actionlint clean; PR opened; the `claude-review / claude-review` check runs green on the PR.

- [ ] **Step 3: Audit branch protection and merge each PR**

For each `<repo>`:
```bash
gh api repos/jluszcz/<repo>/branches/main/protection --jq '.required_status_checks.checks[]?.context' 2>/dev/null || echo "none"
```
Update any old bare required-check name to `claude-review / claude-review`, then:
```bash
cd /Users/jacob/Documents/Programs/<repo>
gh pr merge --squash --delete-branch
```

---

## Task 5: Roll out to JS/Python repos (migrate `dependabot-auto-merge.yml`)

These have `claude.yml` and `claude-code-review.yml` plus a **narrower** `dependabot-auto-merge.yml`: **Elonulator, EndTimes, LottoCheck, Outwatch, plexport, Seen.** The old file is deleted and replaced by an `auto-merge.yml` caller (broad logic).

**Files (per repo):**
- Modify (replace whole body): `<repo>/.github/workflows/claude.yml`
- Modify (replace whole body): `<repo>/.github/workflows/claude-code-review.yml`
- Delete: `<repo>/.github/workflows/dependabot-auto-merge.yml`
- Create: `<repo>/.github/workflows/auto-merge.yml`

- [ ] **Step 1: Confirm each repo's file layout**

Run:
```bash
cd /Users/jacob/Documents/Programs
for r in Elonulator EndTimes LottoCheck Outwatch plexport Seen; do
  echo "== $r =="
  ls "$r/.github/workflows/" | grep -E 'claude|auto-merge|dependabot'
done
```
Expected: each shows `claude.yml`, `claude-code-review.yml`, and `dependabot-auto-merge.yml`.

- [ ] **Step 2: For each repo, branch, migrate all four files, validate, PR**

For each `<repo>`:
```bash
cd /Users/jacob/Documents/Programs/<repo>
git switch -c shared-workflows -t origin/main
git rm .github/workflows/dependabot-auto-merge.yml
# overwrite claude.yml and claude-code-review.yml with the Task 3 caller bodies
# create auto-merge.yml with the Task 3 auto-merge caller body
actionlint .github/workflows/claude.yml .github/workflows/claude-code-review.yml .github/workflows/auto-merge.yml
git add .github/workflows/claude.yml .github/workflows/claude-code-review.yml .github/workflows/auto-merge.yml
git commit -m "refactor: use shared github-utils reusable workflows; unify auto-merge"
git push -u origin shared-workflows
gh pr create --fill --title "Use shared github-utils reusable workflows"
```
Expected per repo: `dependabot-auto-merge.yml` gone; `auto-merge.yml` caller present; actionlint clean; review check green.

- [ ] **Step 3: Audit branch protection and merge each PR**

Same as Task 4 Step 3 for each of the six repos.

---

## Task 6: Migrate remaining claude-only repos and finalize

Remaining repos with `claude.yml` / `claude-code-review.yml` but no auto-merge to unify: **Renamer, todoer, jluszcz.com, skills** (and `dotfiles` if it carries these workflows — confirm in Step 1). Renamer and todoer additionally still have the functionally **older** `claude-code-review.yml` (job-level skip); replacing them with the caller fixes that straggler automatically.

**Files (per repo):**
- Modify (replace whole body): `<repo>/.github/workflows/claude.yml`
- Modify (replace whole body): `<repo>/.github/workflows/claude-code-review.yml`

- [ ] **Step 1: Confirm which repos carry the two claude workflows**

Run:
```bash
cd /Users/jacob/Documents/Programs
for r in Renamer todoer jluszcz.com skills dotfiles; do
  echo "== $r =="
  ls "$r/.github/workflows/" 2>/dev/null | grep -E 'claude' || echo "(no claude workflows)"
done
```
Expected: Renamer, todoer, jluszcz.com, skills show both claude files. Skip any repo/file not present.

- [ ] **Step 2: For each repo, branch, replace the two claude files, validate, PR**

For each `<repo>` that has them:
```bash
cd /Users/jacob/Documents/Programs/<repo>
git switch -c shared-workflows -t origin/main
# overwrite claude.yml and claude-code-review.yml with the Task 3 caller bodies
actionlint .github/workflows/claude.yml .github/workflows/claude-code-review.yml
git add .github/workflows/claude.yml .github/workflows/claude-code-review.yml
git commit -m "refactor: use shared github-utils reusable workflows"
git push -u origin shared-workflows
gh pr create --fill --title "Use shared github-utils reusable workflows"
```

- [ ] **Step 3: Audit branch protection and merge each PR**

Same as Task 4 Step 3.

- [ ] **Step 4 (optional, per brainstorm): Add broad auto-merge to Renamer and todoer**

Renamer and todoer have Dependabot but no auto-merge today. If desired, in the same branch add `auto-merge.yml` with the Task 3 auto-merge caller body, `actionlint` it, and include it in the PR. Skip if not wanted. (jluszcz.com and skills have no `dependabot.yml`, so auto-merge is not added to them here.)

- [ ] **Step 5: Final drift check across all migrated repos**

Run:
```bash
cd /Users/jacob/Documents/Programs
grep -RL "github-utils/.github/workflows" */.github/workflows/claude.yml */.github/workflows/claude-code-review.yml 2>/dev/null
```
Expected: empty output (every remaining `claude.yml`/`claude-code-review.yml` is now a caller). Any file listed is a missed migration — revisit it.
