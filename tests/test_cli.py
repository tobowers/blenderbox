"""Offline help and skill installation contracts, independent of Blender."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from blenderbox.cli import parser


class OfflineCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.env = {**os.environ, "BLENDERBOX_HOME": str(self.root / "must-not-start"),
                    "BLENDERBOX_BLENDER": "/missing/blender",
                    "CODEX_HOME": str(self.root / "codex"),
                    "XDG_CONFIG_HOME": str(self.root / "config"), "HOME": str(self.root)}

    def tearDown(self):
        self.assertFalse((self.root / "must-not-start").exists(), "Offline commands started a daemon")
        self.temp.cleanup()

    def cli(self, *args, success=True):
        run = subprocess.run([sys.executable, "-m", "blenderbox.cli", *args], env=self.env,
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0 if success else 1, run.stderr)
        return run

    def test_help_every_command_and_nested_topic_offline(self):
        def walk(node, parts=()):
            for action in node._actions:
                if hasattr(action, "choices") and isinstance(action.choices, dict):
                    for name, child in action.choices.items():
                        path = (*parts, name)
                        self.assertTrue(self.cli(*path, "--help").stdout.strip())
                        self.assertTrue(self.cli("help", *path).stdout.strip())
                        walk(child, path)
        walk(parser())
        self.assertGreater(len(self.cli("help", "--all").stdout), 20000)
        error = self.cli("help", "no-such-command", success=False)
        self.assertEqual(json.loads(error.stderr)["type"], "unknown_help_topic")

    def test_bundled_skill_discovery_and_references(self):
        skills = json.loads(self.cli("skills", "list").stdout)
        entry = next(s for s in skills if s["name"] == "blenderbox")
        self.assertIn("references/cli.md", entry["files"])
        self.assertIn("references/python.md", entry["files"])
        for file in entry["files"]:
            self.assertTrue(self.cli("skills", "show", "--file", file).stdout)
        shown = json.loads(self.cli("skills", "show", "--json").stdout)
        self.assertEqual(shown["result"]["file"], "SKILL.md")
        unknown = self.cli("skills", "show", "not-a-skill", success=False)
        self.assertEqual(json.loads(unknown.stderr)["type"], "unknown_skill")
        escape = self.cli("skills", "show", "--file", "../outside", success=False)
        self.assertEqual(json.loads(escape.stderr)["type"], "skill_file_not_found")

    def test_install_dry_run_idempotence_conflicts_and_force(self):
        parent = self.root / "custom-skills"
        planned = json.loads(self.cli("skills", "install", "--path", str(parent), "--dry-run").stdout)
        self.assertFalse(parent.exists())
        self.assertEqual(planned["installations"][0]["status"], "would_install")
        installed = json.loads(self.cli("skills", "install", "--path", str(parent)).stdout)
        target = Path(installed["installations"][0]["path"])
        original = (target / "SKILL.md").read_text()
        self.assertTrue((target / "references/cli.md").is_file())
        self.assertEqual(json.loads(self.cli("skills", "install", "--path", str(parent)).stdout)
                         ["installations"][0]["status"], "unchanged")
        (target / "SKILL.md").write_text("local edit")
        failure = self.cli("skills", "install", "--path", str(parent), success=False)
        self.assertEqual(json.loads(failure.stderr)["type"], "skill_exists")
        self.assertEqual((target / "SKILL.md").read_text(), "local edit")
        planned = json.loads(self.cli("skills", "install", "--path", str(parent), "--dry-run").stdout)
        self.assertEqual(planned["installations"][0]["status"], "conflict")
        self.cli("skills", "install", "--path", str(parent), "--force")
        self.assertEqual((target / "SKILL.md").read_text(), original)

    def test_agent_destinations_and_preflight(self):
        all_targets = json.loads(self.cli("skills", "install", "--agent", "all").stdout)["installations"]
        expected = {self.root / "codex/skills/blenderbox", self.root / ".claude/skills/blenderbox",
                    self.root / "config/opencode/skills/blenderbox", self.root / ".agents/skills/blenderbox"}
        self.assertEqual({Path(p["path"]) for p in all_targets}, expected)
        for target in expected:
            self.assertTrue((target / "SKILL.md").is_file())
        # No earlier target is modified when a later target conflicts.
        codex = self.root / "codex/skills/blenderbox"
        import shutil
        shutil.rmtree(codex)
        claude = self.root / ".claude/skills/blenderbox/SKILL.md"
        claude.write_text("edited")
        self.cli("skills", "install", "--agent", "codex", "--agent", "claude", success=False)
        self.assertFalse(codex.exists())


if __name__ == "__main__":
    unittest.main()
