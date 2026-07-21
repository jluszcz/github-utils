import unittest

from release import build_commands, current_major, parse_args, resolve_target


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
        cmds = build_commands(
            "v2", "abc123", "v2: break", is_move=False, remote="origin"
        )
        self.assertEqual(
            cmds,
            [
                ["git", "tag", "-a", "v2", "abc123", "-m", "v2: break"],
                ["git", "push", "origin", "v2"],
            ],
        )


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


if __name__ == "__main__":
    unittest.main()
