#!/usr/bin/env python3
"""Release this repo: move the current major version tag to origin/main's tip,
or cut the next major with --breaking."""

import argparse
import re
import shlex
import subprocess
import sys

_VERSION_RE = re.compile(r"^v(\d+)$")
_MESSAGE_PREFIX_RE = re.compile(r"^v\d+\s*:")


def has_version_prefix(message):
    return bool(_MESSAGE_PREFIX_RE.match(message))


def format_message(tag, message):
    return f"{tag}: {message}"


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
    parser.add_argument(
        "-m",
        "--message",
        required=True,
        help="Annotated-tag message, without the 'vN:' prefix (added automatically).",
    )
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
    parser.add_argument(
        "--remote", default="origin", help="Remote name (default: origin)."
    )
    parser.add_argument(
        "--branch", default="main", help="Branch to tag (default: main)."
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if has_version_prefix(args.message):
        print(
            "error: -m message must not include a 'vN:' prefix (added automatically)",
            file=sys.stderr,
        )
        return 1

    # 1. Fetch so the tag lands on the true remote tip.
    print(f"Fetching {args.remote}/{args.branch}...")
    try:
        git_output(["fetch", args.remote, args.branch])
    except subprocess.CalledProcessError:
        print(f"error: git fetch {args.remote} {args.branch} failed", file=sys.stderr)
        return 1

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
    message = format_message(tag, args.message)
    commands = build_commands(tag, sha, message, is_move, args.remote)

    # 4. Summarize.
    action = "MOVE (force)" if is_move else "CREATE"
    print(f"\n{action} tag {tag} -> {ref} ({sha[:12]})")
    print(f"  message: {message}")
    for cmd in commands:
        print("  $ " + shlex.join(cmd))

    if args.dry_run:
        print("\n--dry-run: nothing executed.")
        return 0

    # 5. Confirm, then run.
    if not args.yes:
        reply = input("\nProceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    try:
        for cmd in commands:
            subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        print(f"error: command failed: {shlex.join(cmd)}", file=sys.stderr)
        return 1

    print(f"\nReleased {tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
