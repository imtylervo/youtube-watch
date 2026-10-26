"""Subtitle choice must follow the video's own language, not alphabetical order."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pick-vtt.py"


def pick(names, lang):
    with tempfile.TemporaryDirectory() as tmp:
        for n in names:
            (Path(tmp) / n).write_text("WEBVTT\n", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPT), tmp, lang],
            capture_output=True, text=True,
        )
        return r.returncode, Path(r.stdout.strip()).name if r.stdout.strip() else ""


class PickVttTests(unittest.TestCase):
    def test_original_language_beats_machine_translation(self):
        rc, name = pick(["transcript.en.vtt", "transcript.vi.vtt"], "vi")
        self.assertEqual((rc, name), (0, "transcript.vi.vtt"))

    def test_orig_track_preferred_over_plain(self):
        rc, name = pick(["transcript.en.vtt", "transcript.vi.vtt", "transcript.vi-orig.vtt"], "vi")
        self.assertEqual(name, "transcript.vi-orig.vtt")

    def test_falls_back_to_english_when_original_missing(self):
        rc, name = pick(["transcript.de.vtt", "transcript.en.vtt"], "vi")
        self.assertEqual(name, "transcript.en.vtt")

    def test_unknown_language_prefers_orig_track(self):
        rc, name = pick(["transcript.en.vtt", "transcript.vi-orig.vtt"], "NA")
        self.assertEqual(name, "transcript.vi-orig.vtt")

    def test_english_video_takes_english(self):
        rc, name = pick(["transcript.en.vtt", "transcript.fr.vtt"], "en")
        self.assertEqual(name, "transcript.en.vtt")

    def test_no_vtt_exits_nonzero(self):
        rc, name = pick([], "en")
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
