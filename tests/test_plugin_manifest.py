"""The plugin manifests must stay installable and in step with VERSION."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PluginManifestTests(unittest.TestCase):
    def test_plugin_version_matches_version_file(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], (ROOT / "VERSION").read_text().strip())

    def test_marketplace_lists_the_repo_root(self):
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual([p["source"] for p in market["plugins"]], ["./"])
        self.assertEqual(market["plugins"][0]["name"], "youtube-watch")

    def test_skill_calls_its_script_through_the_skill_dir(self):
        skill = (ROOT / "SKILL.md").read_text()
        self.assertIn("${CLAUDE_SKILL_DIR}/scripts/extract-v3.sh", skill)
        # the fixed path appears only in the note for tools other than Claude Code
        self.assertEqual(skill.count("~/.claude/skills/youtube-watch/scripts"), 1)


if __name__ == "__main__":
    unittest.main()
