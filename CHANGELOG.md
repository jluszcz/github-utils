# Changelog

## v2 — 2026-09-01 (Dependabot merges trigger downstream workflows)

`auto-merge.yml` takes two optional secrets, `APP_ID` and `APP_PRIVATE_KEY`, and
merges with a GitHub App installation token when they are set. Without them it
falls back to the default `GITHUB_TOKEN` and behaves exactly as before, so no
caller has to change anything to take this release.

GitHub creates no workflow runs for events triggered by `GITHUB_TOKEN`
(`workflow_dispatch` and `repository_dispatch` are the only exceptions), so
every auto-merged bump in the portfolio has been landing on `main` as an inert
event: no `push` run, no `pull_request: closed` run. Three same-day merges show
it — `LottoCheck`, `EndTimes`, and `github-utils` each recorded a successful
`Auto-Merge` and no `push` run on `main`, while a human-merged PR in `mbtalerts`
got its `push` run. `mbtalerts`, `MovieList`, `BurgerList`, `LogStreamGC`,
`ListOfLists-rs`, `JakeSky-rs`, and `StarList` gate deploys on `push`, so their
dependency bumps merged and never shipped. `auto-release.yml` in this repo has
never run: every execution in its history is `skipped`, and the one PR it was
written for produced no run at all — `v2` was tagged by hand.

An App-triggered merge is a real event, so those runs happen. It also clears a
second, latent failure. Workflows triggered by `pull_request` events whose actor
is `dependabot[bot]` get a read-only `GITHUB_TOKEN` regardless of the
`permissions:` block, so `auto-release.yml` could not have pushed a tag even if
it had run. With the App as merger the actor on `pull_request: closed` is the
App, not `dependabot[bot]`, and the tag push works with no change to that file.

Restoring the push event means an auto-merged bump now runs CI and deploys with
no human in the loop. That is what those workflows already declare; the
recursion guard has been suppressing it. Accepted deliberately rather than
gated.

Backward-compatible: optional secrets with a fallback. `LambdUpdate` pins `@v1`
and does not receive this. Any other repo that never gets the secrets keeps
today's behavior, silently.

## v2 — 2026-08-21 (Terraform format & validate)

New `terraform-ci.yml`: `terraform fmt -check -recursive -diff` from the repo
root, then `terraform init -backend=false` and `terraform validate` per root
directory. Both halves already existed, copy-pasted, in `AmazonWebServices` and
`MisterManager`; every other repo carrying `.tf` files had no check at all.

The optional `directories` input (newline-separated, default `.`) covers repos
whose Terraform is not at the root. `ListOfLists-rs` is the reason it exists: it
has no root `.tf` and five separate roots, each with its own
`.terraform.lock.hcl`.

`-backend=false` is what makes this runnable as an ordinary CI job — no S3
backend, no AWS credentials, no OIDC — so callers need nothing beyond the
default `contents: read`.

Backward-compatible: a new workflow plus an optional input with a default. The
two repos that had the check inline see their status check renamed from
`Format & Validate` to `terraform / Format & Validate`, which is a caller-side
change, not a break in this repo's API.

## v2 — 2026-08-18 (Review agents run in the foreground)

`claude-code-review.yml` extends `prompt` with an instruction to dispatch every
review agent with `run_in_background: false` and not to end the turn until the
findings are posted. This is the actual fix for reviews that finish green having
posted nothing but their progress checklist.

The captured execution log names the cause. `Agent` launches asynchronously
unless told otherwise: all five dispatches returned "Async agent launched
successfully" with an `agentId`, and `run_in_background` was never set. With
nothing to block on, Claude updated the checklist, tried `ScheduleWakeup`, wrote
"I'll just wait for the automatic completion notifications rather than
scheduling a manual wakeup", and ended its turn. A one-shot headless run has no
notification loop, so the session terminated there — `stop_reason: end_turn`,
`is_error: false`, exit 0 — with all five agents killed mid-flight.

That is why it looked intermittent. The runs that produced a real review passed
`run_in_background: false` explicitly; the ones that stalled left it unset and
took the async default. Nothing in the configuration forced the choice either
way, so the same PR could review fine or die depending on how the model phrased
one tool call.

Reproduced on MisterManager #29 (17 turns, 1m 26s, **zero** permission denials,
frozen after "Summarize PR changes"). Denials were never involved: #30 recorded
40 of them and posted a complete review with five inline comments.

Backward-compatible: no new inputs, no new permissions.

## v2 — 2026-08-18 (Reviews can keep their execution log)

`claude-code-review.yml` takes a `debug` input (default `false`). When set, the
job uploads Claude's execution log as a `claude-execution-log` artifact.

Reviews are still stalling after the `Skill` fix below. On MisterManager #27 and
#28 — both with `Skill` in the allowlist — the job ended green in ~2 minutes
having posted only its progress checklist, frozen at the state the working run
writes immediately *before* dispatching its parallel review agents. So the run
dies at the dispatch, and the two earlier diagnoses in this file were both
reached without seeing what Claude actually did.

That is what this input exists to end. The action hides the turn stream, and
rerunning the job with Actions debug logging does not unhide it, so a stalled
review leaves no evidence at all: the only signal in the log is
`permission_denials_count`, an integer. The artifact carries the tool calls
themselves and a `permission_denials` entry per blocked call with its input.

Off by default, and worth turning back off once a review is fixed — the log is
the review verbatim, diff and file contents included.

Backward-compatible: new optional input, no new permissions, no change to a
caller that does not set it.

## v2 — 2026-08-18 (Code review actually runs the review command)

`claude-code-review.yml` adds `Skill` and `Bash(git fetch:*)` to
`--allowedTools`, and drops the `Task` entry added earlier today.

`Skill` is the fix. It is the tool that runs the slash command in `prompt`, and
it was the **first call of every review run** — denied every time. The
`code-review` plugin command therefore never loaded: no five-agent procedure, no
confidence scoring, no output format, and no step instructing Claude to post the
result with `gh pr comment`. What ran instead was a model improvising a review
from the bare prompt string. On a small diff that improvisation converged and
posted something plausible, which is why reviews looked healthy. On a large one
it dispatched four background agents, ended its turn to wait for them, and the
one-shot SDK run terminated with only the progress checklist posted — and green,
since nothing errored.

`Bash(git fetch:*)` removes a secondary thrash: the checkout is `fetch-depth: 1`,
so `origin/main` is absent and every `git log origin/main..HEAD` fails. One run
burned eight consecutive calls on `git fetch` variants before working around it.

**Correcting the previous entry below.** The `Task` entry it added was inert and
its diagnosis was wrong. `Task` is not a tool name in Claude Code 2.1 — subagent
dispatch is `Agent` — and `Agent` is not permission-gated, so no allowlist entry
was ever needed for it. The execution log confirms it: four `Agent` dispatches,
all allowed, zero denials. That change fixed nothing and is reverted here.

Backward-compatible: no new inputs, no new permissions.

## v2 — 2026-08-18 (Code review can dispatch its subagents)

**Superseded: this diagnosis was wrong — see the entry above.**

`claude-code-review.yml` adds `Task` to `--allowedTools`. The `code-review`
plugin command is subagent-driven end to end — its steps read "use a Haiku
agent to check eligibility", "launch 5 parallel Sonnet agents to review", "for
each issue, launch a Haiku agent to score it" — and `Task` was in neither the
action's base allowlist (`Glob`, `Grep`, `LS`, `Read`) nor ours, so every
dispatch was denied.

The failure was quiet and size-dependent, which is why it took this long to
notice. On a small diff Claude gave up on the fan-out and reviewed the files
itself, so reviews looked fine. On a large one it dispatched, absorbed a dozen
denials, and ended its turn having posted only the progress checklist — with
the job green, since a denied tool call is not an execution error.

Backward-compatible: no new inputs, no new permissions. Subagents inherit the
same allowlist, so they are still limited to reading plus the `git`/`gh`
subcommands already listed.

## v2 — 2026-08-17 (Claude can push commits)

`claude.yml`'s job now requests `contents: write` instead of `contents: read`.
The App token `claude-code-action` mints through the OIDC exchange is scoped
down to the job's declared permissions, so under `contents: read` an `@claude`
comment asking for a fix would produce the commit locally and then fail to push
it with `remote: Write access to repository not granted` / HTTP 403 — after the
work was already done.

Backward-compatible: no new inputs, and the reusable job's permissions are a
ceiling rather than a floor. **Callers must opt in**, though: a called
workflow's permissions cannot exceed the caller's, and every caller today
declares `contents: read`. Until a caller raises its own `permissions.contents`
to `write`, `@claude` there still cannot push. Callers that should never have
Claude commit can leave theirs at `read`.

## v2 — 2026-08-02 (Surface the reason a deploy's activation fails)

When `aws lambda wait function-updated-v2` fails — the update reached
`LastUpdateStatus: Failed`, or the roughly five-minute poll times out — the
step now follows with `aws lambda get-function` and prints
`Configuration.{LastUpdateStatus,LastUpdateStatusReason,State,StateReason}` to
the job log before exiting non-zero. Previously the only signal was the
waiter's generic "Waiter FunctionUpdatedV2 failed: Waiter encountered a
terminal failure state.", which never surfaces `LastUpdateStatusReason` — the
one field that says *why* the update failed to activate. Backward-compatible:
no new inputs, and no new IAM, since `lambda:GetFunction` already covers
`get-function`.

## v2 — 2026-08-02 (Deploy updates the function)

`deploy-lambda.yml` now calls `UpdateFunctionCode` after copying the zip to the
code bucket, and waits for the update to complete successfully, so a failed
deploy reddens CI instead of surfacing as a log line in someone else's Lambda.
It retries `ResourceConflictException` up to three attempts with 1s/2s backoff
and fails immediately on anything else.

**Breaking:** the `${project}.github-deploy` role now needs
`lambda:UpdateFunctionCode` and `lambda:GetFunction` on the target function, and
`s3:GetObject` in addition to `s3:PutObject` on the artifact object —
`update-function-code` with an S3 source has Lambda fetch the object using the
caller's credentials, not the function's execution role. Grant all four before
bumping a caller's pin to `@v2`. The function name is `project`; callers whose
function is named differently need a change here first.

(This requirement was initially documented as three permissions, missing
`s3:GetObject`; a real deploy's `AccessDeniedException` surfaced the gap and
this entry was corrected in place.)

This retires `LambdUpdate`, the Lambda that watched the code bucket for `.zip`
objects and called `UpdateFunctionCode` on the caller's behalf. Its
`function.names` object-metadata fan-out — one artifact updating several
functions — has no replacement, because no caller ever used it.

## v1 — 2026-08-01 (Review on open, not on every push)

`claude-code-review.yml`'s review step now skips `synchronize` events, so a PR
is reviewed when it is opened, reopened, or marked ready for review, but not on
every follow-up push. As with the dependabot skip, the step is skipped rather
than the job, so the job still reports success on the new head commit and a
required status check keeps passing. Callers should keep `synchronize` in their
`pull_request` trigger types for that reason — no caller change is needed.
Re-running the job from the Actions UI replays the original event and so still
skips; to get a review on a later push, comment `@claude review this PR`, which
`claude.yml` already handles. No change to caller inputs or job names.

## v1 — 2026-08-01 (Minify and upload)

Added reusable `minify-and-upload.yml`, extracted from the identical
`workflow.yml` copies in `BurgerList`, `MovieList`, and `StarList`: minify a
list JSON with `jq`, assume `${project}.github-update` over OIDC, and copy the
result to `s3://${bucket-prefix}-${account}-${region}-an/${s3-key-prefix}.json`.
Takes required `aws-region`, `project`, `s3-key-prefix`, and `bucket-prefix`
inputs plus an `aws-account-id` secret, matching `deploy-lambda.yml`'s shape.
Callers must grant `id-token: write`. Relative to the per-repo copies it moves
`actions/checkout` v6 → v7 and `aws-actions/configure-aws-credentials` from the
mutable `v6.0.0` tag to the SHA pinned at v6.2.3. Additive — no change to
existing callers.

## v1 — 2026-07-26 (Re-enable Claude Code Review)

`claude-code-review.yml` reviews PRs again. The `ENABLE_CLAUDE_REVIEW`
repo/org variable gate is gone — reverting the previous entry — and the step is
back to the dependabot/`Deps-*` skip, so every other PR gets a review. The
variable is no longer read; repos that set it can drop it. Callers that want
reviews off should stop calling this workflow. No change to caller inputs or job
names.

## v1 — 2026-07-25 (Disable Claude Code Review)

`claude-code-review.yml`'s review step now skips by default, gated on the
`ENABLE_CLAUDE_REVIEW` repo/org variable (unset/`false` by default); the job
still succeeds, so the required check keeps passing without commenting on any
PR. A plain `if: false` tripped actionlint's `if-cond` constant-expression
check, hence the variable gate instead. Replaces the prior
dependabot/`Deps-*`-only skip. Additive — no change to caller inputs or job
names.

## v1 — 2026-07-25 (Fix concurrency group collisions)

Concurrency groups now include the inputs that identify a call. Inside a called
workflow `github.workflow` is the *caller's* workflow name, so two jobs calling
the same reusable workflow from one caller computed an identical group and, with
`cancel-in-progress: true`, cancelled each other. This broke multi-region Lambda
deploys — the exact pattern `README.md` recommends — in `LambdUpdate` and
`LogStreamGC`, where one region's deploy could be cancelled by the other's.

`deploy-lambda` keys on `project` + `aws-region`, `lambda-package` on `project` +
`target`, `rust-ci` on `runs-on` + `target` + `all-features`, and `node-ci` on
`node-version`. `python-ci` takes no inputs and is unchanged. Additive — no
change to caller inputs or job names.

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
