# Release Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scripts/release.py` — one command that moves the current major version tag to the tip of `origin/main`, or cuts the next major with `--breaking`.

**Architecture:** A single Python script with pure helper functions (version parsing, target resolution, git-command construction) separated from a thin `main()` that shells out to git. Pure functions are unit-tested with stdlib `unittest`; no third-party dependencies. The script never edits `CHANGELOG.md` — that's a PR responsibility, enforced by a new repo `CLAUDE.md` rule.

**Tech Stack:** Python 3 (stdlib only: `argparse`, `subprocess`, `sys`, `re`, `unittest`), git.

## Global Constraints

- **No third-party dependencies** — stdlib only, so the otherwise dependency-free repo stays that way. Tests run via `python -m unittest`.
- **Script never edits `CHANGELOG.md`** — the changelog is updated inside each feature PR.
- **Tags point at `origin/<branch>`'s SHA**, not local `HEAD`. Always `git fetch` first.
- **Moving tag = force** (`git tag -fa` + `git push --force`); **new major = no force** (`git tag -a` + `git push`).
- **Commit style:** repo uses Conventional Commits (`feat:`, `docs:`, `chore:`). Commit onto the current feature branch `ReleaseScript` (never `main`).
- **Executable:** `scripts/release.py` has a `#!/usr/bin/env python3` shebang and is `chmod +x`.

---

### Task 1: Pure helper functions + tests

Build the testable core: version parsing, target resolution, and git-command construction. No git calls, no side effects — this whole task is pure functions and their unit tests.

**Files:**
- Create: `scripts/release.py`
- Create: `scripts/test_release.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `current_major(tags: list[str]) -> int` — highest `N` among tags matching `^v(\d+)$`; `0` if none.
  - `resolve_target(current: int, breaking: bool) -> tuple[str, bool]` — returns `(tag_name, is_move)`. Default: `(f"v{current}", True)`. Breaking: `(f"v{current+1}", False)`.
  - `build_commands(tag: str, sha: str, message: str, is_move: bool, remote: str) -> list[list[str]]` — returns the git command sequence as arg-lists.

- [ ] **Step 1: Write the failing tests**

Create `scripts/test_release.py`:

```python
import unittest

from release import build_commands, current_major, resolve_target


class CurrentMajorTest(unittest.TestCase):
    def test_single_tag(self):
        self.assertEqual(current_major(["v1"]), 1)

    def test_picks_highest(self):
        self.assertEqual(current_major(["v1", "v2", "v10"]), 10)

    def test_ignores_non_version_tags(self):
        self.assertEqual(current_major(["v1", "v1.2", "release", "v2beta"]), 1)

    def test_empty(self):
        self.assertEqual(current_major([]), 0)


class ResolveTargetTest(unittest.TestCase):
    def test_default_moves_current(self):
        self.assertEqual(resolve_target(1, breaking=False), ("v1", True))

    def test_breaking_creates_next(self):
        self.assertEqual(resolve_target(1, breaking=True), ("v2", False))

    def test_breaking_with_no_tags_creates_v1(self):
        self.assertEqual(resolve_target(0, breaking=True), ("v1", False))


class BuildCommandsTest(unittest.TestCase):
    def test_move_uses_force(self):
        cmds = build_commands("v1", "abc123", "v1: fix", is_move=True, remote="origin")
        self.assertEqual(
            cmds,
            [
                ["git", "tag", "-fa", "v1", "abc123", "-m", "v1: fix"],
                ["git", "push", "--force", "origin", "v1"],
            ],
        )

    def test_create_omits_force(self):
        cmds = build_commands("v2", "abc123", "v2: break", is_move=False, remote="origin")
        self.assertEqual(
            cmds,
            [
                ["git", "tag", "-a", "v2", "abc123", "-m", "v2: break"],
                ["git", "push", "origin", "v2"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python -m unittest test_release -v`
Expected: FAIL — `ImportError` / `ModuleNotFoundError` (or "cannot import name") because `release.py` has no such functions yet.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/release.py`:

```python
#!/usr/bin/env python3
"""Release this repo: move the current major version tag to origin/main's tip,
or cut the next major with --breaking."""

import re

_VERSION_RE = re.compile(r"^v(\d+)$")


def current_major(tags):
    majors = [int(m.group(1)) for t in tags if (m := _VERSION_RE.match(t))]
    return max(majors) if majors else 0


def resolve_target(current, breaking):
    if breaking:
        return f"v{current + 1}", False
    return f"v{current}", True


def build_commands(tag, sha, message, is_move, remote):
    if is_move:
        return [
            ["git", "tag", "-fa", tag, sha, "-m", message],
            ["git", "push", "--force", remote, tag],
        ]
    return [
        ["git", "tag", "-a", tag, sha, "-m", message],
        ["git", "push", remote, tag],
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python -m unittest test_release -v`
Expected: PASS — all 9 tests OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/release.py scripts/test_release.py
git commit -m "feat(release): add version-tag helper functions"
```

---

### Task 2: CLI, git integration, and `main()`

Wire the pure functions to git: parse args, fetch, read tags, resolve the SHA, confirm, and run the commands. `--dry-run` prints without executing; `--yes` skips the prompt.

**Files:**
- Modify: `scripts/release.py`

**Interfaces:**
- Consumes: `current_major`, `resolve_target`, `build_commands` from Task 1.
- Produces:
  - `git_output(args: list[str]) -> str` — runs `["git", *args]`, returns stripped stdout, raises on non-zero.
  - `parse_args(argv) -> argparse.Namespace` — flags: `-m/--message` (required), `--breaking`, `--dry-run`, `--yes`, `--remote` (default `origin`), `--branch` (default `main`).
  - `main(argv=None) -> int` — orchestration; returns process exit code.

- [ ] **Step 1: Write the failing tests**

Add to `scripts/test_release.py` (extend the existing `from release import ...` line to include `parse_args`, then add the new test class at the bottom before the `__main__` guard):

```python
from release import build_commands, current_major, parse_args, resolve_target
```

```python
class ParseArgsTest(unittest.TestCase):
    def test_message_required(self):
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_defaults(self):
        ns = parse_args(["-m", "v1: fix"])
        self.assertEqual(ns.message, "v1: fix")
        self.assertFalse(ns.breaking)
        self.assertFalse(ns.dry_run)
        self.assertFalse(ns.yes)
        self.assertEqual(ns.remote, "origin")
        self.assertEqual(ns.branch, "main")

    def test_breaking_and_flags(self):
        ns = parse_args(["-m", "v2: break", "--breaking", "--dry-run", "--yes"])
        self.assertTrue(ns.breaking)
        self.assertTrue(ns.dry_run)
        self.assertTrue(ns.yes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python -m unittest test_release -v`
Expected: FAIL — `ImportError: cannot import name 'parse_args'`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/release.py`, add imports at the top (after the existing `import re`):

```python
import argparse
import subprocess
import sys
```

Then append the CLI + orchestration below `build_commands`:

```python
def git_output(args):
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-m", "--message", required=True, help="Annotated-tag message.")
    parser.add_argument(
        "--breaking",
        action="store_true",
        help="Create the next major tag instead of moving the current one.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the git commands without executing or pushing.",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt."
    )
    parser.add_argument("--remote", default="origin", help="Remote name (default: origin).")
    parser.add_argument("--branch", default="main", help="Branch to tag (default: main).")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # 1. Fetch so the tag lands on the true remote tip.
    print(f"Fetching {args.remote}/{args.branch}...")
    git_output(["fetch", args.remote, args.branch])

    # 2. Resolve the remote tip SHA.
    ref = f"{args.remote}/{args.branch}"
    try:
        sha = git_output(["rev-parse", "--verify", f"{ref}^{{commit}}"])
    except subprocess.CalledProcessError:
        print(f"error: cannot resolve {ref}", file=sys.stderr)
        return 1

    # 3. Determine current major and the target tag.
    tags = git_output(["tag", "-l", "v*"]).split()
    current = current_major(tags)
    if not args.breaking and current == 0:
        print(
            "error: no version tag to move; use --breaking to cut the first release",
            file=sys.stderr,
        )
        return 1

    tag, is_move = resolve_target(current, args.breaking)
    commands = build_commands(tag, sha, args.message, is_move, args.remote)

    # 4. Summarize.
    action = "MOVE (force)" if is_move else "CREATE"
    print(f"\n{action} tag {tag} -> {ref} ({sha[:12]})")
    print(f"  message: {args.message}")
    for cmd in commands:
        print("  $ " + " ".join(cmd))

    if args.dry_run:
        print("\n--dry-run: nothing executed.")
        return 0

    # 5. Confirm, then run.
    if not args.yes:
        reply = input("\nProceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    for cmd in commands:
        subprocess.run(cmd, check=True)

    print(f"\nReleased {tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python -m unittest test_release -v`
Expected: PASS — all 12 tests OK.

- [ ] **Step 5: Verify the CLI end-to-end with `--dry-run`**

Run (from repo root): `python scripts/release.py -m "v1: test" --dry-run`
Expected output includes a fetch line, then:
```
MOVE (force) tag v1 -> origin/main (<sha>)
  message: v1: test
  $ git tag -fa v1 <sha> -m v1: test
  $ git push --force origin v1

--dry-run: nothing executed.
```
Also run: `python scripts/release.py -m "v2: break" --breaking --dry-run`
Expected: `CREATE tag v2 -> origin/main ...` with `git tag -a v2 ...` and `git push origin v2` (no `--force`).

Confirm no tag was created: `git tag -l 'v*'` still shows only `v1`.

- [ ] **Step 6: Make the script executable and commit**

```bash
chmod +x scripts/release.py
git add scripts/release.py scripts/test_release.py
git commit -m "feat(release): add CLI, git integration, and main()"
```

---

### Task 3: Docs — `CLAUDE.md` rule and README update

Add the repo `CLAUDE.md` that enforces the changelog-in-PR rule, and update the README's "Releasing changes" section to lead with the script.

**Files:**
- Create: `CLAUDE.md`
- Modify: `README.md` (the "Releasing changes (moving tags)" section, lines ~25-70)

**Interfaces:**
- Consumes: the finished `scripts/release.py` CLI from Task 2.
- Produces: documentation only.

- [ ] **Step 1: Create `CLAUDE.md`**

Create `/Users/jacob/Documents/Programs/github-utils/CLAUDE.md`:

```markdown
# CLAUDE.md

Reusable GitHub Actions workflows shared across `jluszcz` repos. See `README.md`
for the versioning model and caller examples.

## Changelog is updated in the PR

Every PR that changes workflow behavior MUST add an entry to `CHANGELOG.md` in
the same PR, under a `## vN — YYYY-MM-DD (short title)` heading, where `vN` is
the major it will ship under:

- Backward-compatible change (moves `v1`) → heading `## v1 — <date> (...)`.
- Breaking change (cuts the next major) → heading `## v2 — <date> (...)`.

The release script does NOT touch `CHANGELOG.md`; it only moves/creates the tag,
so the changelog must already be correct at release time.

## Releasing

After the PR is merged, cut the release with the script (it tags `origin/main`'s
tip):

- Backward-compatible: `scripts/release.py -m "v1: <what changed>"`
- Breaking: `scripts/release.py --breaking -m "v2: <what changed>"`

Preview with `--dry-run`. See `README.md` → "Releasing changes" for details.
```

- [ ] **Step 2: Update the README "Releasing changes" section**

In `README.md`, replace the `### Patch / minor — move \`v1\`` and `### Breaking — cut \`v2\`` subsections' manual command blocks so the script leads and the manual commands remain as the underlying reference.

Replace this block (the patch/minor code fence, README.md ~lines 33-43):

````markdown
Backward-compatible fixes (version bumps, condition tweaks, new *optional*
inputs) reuse the existing major tag. After merging the change to `main`:

```bash
git checkout main && git pull
git tag -fa v1 -m "v1: <what changed>"   # -f re-points the existing tag
git push --force origin v1
```

Every consumer picks it up on its next run. Record the move in `CHANGELOG.md` in
the same PR as the change.
````

with:

````markdown
Backward-compatible fixes (version bumps, condition tweaks, new *optional*
inputs) reuse the existing major tag. Record the change in `CHANGELOG.md` in the
same PR (see `CLAUDE.md`). After merging to `main`, cut the release:

```bash
scripts/release.py -m "v1: <what changed>"
```

The script fetches `origin/main`, moves `v1` to its tip, and force-pushes the
tag; every consumer picks it up on its next run. Preview with `--dry-run`. Under
the hood it runs:

```bash
git tag -fa v1 <origin/main sha> -m "v1: <what changed>"   # -f re-points the tag
git push --force origin v1
```
````

Then replace this block (the breaking code fence, README.md ~lines 50-55):

````markdown
```bash
git checkout main && git pull
git tag -a v2 -m "v2: <what changed>"
git push origin v2
```
````

with:

````markdown
```bash
scripts/release.py --breaking -m "v2: <what changed>"
```

The script creates the next major tag (`v2`) on `origin/main`'s tip and pushes
it (no force — it's a new tag). Under the hood:

```bash
git tag -a v2 <origin/main sha> -m "v2: <what changed>"
git push origin v2
```
````

- [ ] **Step 3: Verify docs reference the real CLI**

Run: `python scripts/release.py --help`
Confirm the flags shown (`-m/--message`, `--breaking`, `--dry-run`, `--yes`, `--remote`, `--branch`) match what `CLAUDE.md` and `README.md` describe.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document release script and changelog-in-PR rule"
```

---

## Notes for the executor

- **Import mechanics:** tests import from `release` (not `scripts.release`), so run `unittest` from inside `scripts/` (`cd scripts && python -m unittest test_release -v`), or set `PYTHONPATH=scripts`. There is no `__init__.py` and none is needed.
- **Do not create any real tags** during implementation — only Task 2 Step 5's `--dry-run` invocations, which create nothing. Verify with `git tag -l 'v*'` afterward.
- **Branch:** all commits land on the existing `ReleaseScript` feature branch.
