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
