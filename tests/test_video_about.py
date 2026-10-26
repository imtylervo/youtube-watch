"""The author's own title / description / chapters go at the top of understanding.md, so
machine-misheard names can be checked against them."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build-understanding.py"

META = {
    "title": "An Agent That Manages Other Agents",
    "channel": "Sơn BS",
    "upload_date": "20260901",
    "duration_string": "9:47",
    "description": "Open Affiliate, Kyma API, Afiter.\nLink: https://example.com/x",
    "chapters": [
        {"start_time": 0, "end_time": 120, "title": "Intro"},
        {"start_time": 120, "end_time": 300, "title": "Task board"},
    ],
}


def build(meta, index="frame_0001.jpg\t00:00\tnormal", transcript="00:01  hello there"):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "frame_index.txt").write_text(index, encoding="utf-8")
        (d / "transcript.txt").write_text(transcript, encoding="utf-8")
        (d / "header.md").write_text("# Header\n", encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), str(d), "--header", str(d / "header.md")]
        if meta is not None:
            (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            cmd += ["--meta", str(d / "meta.json")]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


class AboutTests(unittest.TestCase):
    def test_title_channel_date_and_description_are_shown(self):
        out = build(META)
        self.assertIn("## About this video", out)
        self.assertIn("**Title:** An Agent That Manages Other Agents", out)
        self.assertIn("Sơn BS", out)
        self.assertIn("2026-09-01", out)
        self.assertIn("Open Affiliate, Kyma API, Afiter.", out)

    def test_chapters_are_listed_with_times(self):
        out = build(META)
        self.assertIn("00:00 Intro", out)
        self.assertIn("02:00 Task board", out)

    def test_reader_is_told_to_check_names_against_the_description(self):
        self.assertIn("check", build(META).lower())
        self.assertIn("spell", build(META).lower())

    def test_long_description_is_cut(self):
        meta = dict(META, description="x" * 5000)
        out = build(meta)
        self.assertLess(out.count("x"), 1700)
        self.assertIn("…", out)

    def test_missing_fields_do_not_crash(self):
        out = build({"title": "Only a title", "description": None, "chapters": None})
        self.assertIn("Only a title", out)
        self.assertNotIn("Chapters", out)

    def test_no_meta_means_no_about_section(self):
        self.assertNotIn("About this video", build(None))

    def test_unreadable_meta_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "frame_index.txt").write_text("frame_0001.jpg\t00:00\tnormal", encoding="utf-8")
            (d / "transcript.txt").write_text("00:01  hello", encoding="utf-8")
            (d / "meta.json").write_text("not json", encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(d), "--meta", str(d / "meta.json")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("hello", r.stdout)


if __name__ == "__main__":
    unittest.main()
