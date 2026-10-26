"""Long videos: understanding.md becomes a contents page; the timeline lives in sections/."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build-understanding.py"


def mmss(sec):
    return f"{sec // 60:02d}:{sec % 60:02d}"


def make_video(seconds, frame_every=10, line_every=5):
    """Frames every 10s, one unique speech line every 5s (text encodes its second)."""
    index = "\n".join(f"frame_{i + 1:04d}.jpg\t{mmss(s)}\tnormal"
                      for i, s in enumerate(range(0, seconds, frame_every)))
    lines = "\n".join(f"{mmss(s)}  L{s:05d} " + "word " * 12 for s in range(0, seconds, line_every))
    return index, lines


def build(index, transcript, meta=None, workdir=None):
    tmp = tempfile.TemporaryDirectory()
    d = Path(workdir or tmp.name)
    (d / "frame_index.txt").write_text(index, encoding="utf-8")
    (d / "transcript.txt").write_text(transcript, encoding="utf-8")
    (d / "header.md").write_text("# Header\n", encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), str(d), "--header", str(d / "header.md")]
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        cmd += ["--meta", str(d / "meta.json")]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    sections = {p.name: p.read_text(encoding="utf-8") for p in sorted((d / "sections").glob("*.md"))}
    return tmp, out, sections


class SectionTests(unittest.TestCase):
    def test_short_video_stays_one_file(self):
        tmp, out, sections = build(*make_video(600))
        self.addCleanup(tmp.cleanup)
        self.assertEqual(sections, {})
        self.assertNotIn("## Contents", out)
        self.assertIn("### [00:00] frame_0001.jpg", out)

    def test_long_video_becomes_contents_plus_section_files(self):
        tmp, out, sections = build(*make_video(7200))
        self.addCleanup(tmp.cleanup)
        self.assertGreaterEqual(len(sections), 3)
        self.assertIn("## Contents", out)
        self.assertNotIn("### [", out)                 # the timeline is not in the main file
        self.assertLess(len(out), 20000)               # main file stays small
        for name in sections:
            self.assertIn(f"sections/{name}", out)

    def test_every_speech_line_is_in_exactly_one_section(self):
        index, transcript = make_video(7200)
        tmp, out, sections = build(index, transcript)
        self.addCleanup(tmp.cleanup)
        joined = "\n".join(sections.values())
        for s in range(0, 7200, 5):
            self.assertEqual(joined.count(f"L{s:05d} "), 1, s)

    def test_contents_entries_have_range_frames_and_opening_words(self):
        tmp, out, sections = build(*make_video(7200))
        self.addCleanup(tmp.cleanup)
        entries = [l for l in out.splitlines() if l.startswith("- [")]
        self.assertEqual(len(entries), len(sections))
        self.assertRegex(entries[0], r"^- \[00:00–\d+:\d{2}\] \*\*Part 1\*\*")
        self.assertIn("frames", entries[0])
        self.assertIn("L00000", entries[0])            # the section's opening words

    def test_author_chapters_become_the_sections(self):
        chapters = [{"start_time": s, "end_time": s + 1200, "title": f"Chapter {i + 1}"}
                    for i, s in enumerate(range(0, 7200, 1200))]
        tmp, out, sections = build(*make_video(7200), meta={"title": "t", "chapters": chapters})
        self.addCleanup(tmp.cleanup)
        self.assertEqual(len(sections), 6)
        for i in range(6):
            self.assertIn(f"**Chapter {i + 1}**", out)
        third = [t for n, t in sections.items() if "Chapter 3" in t.splitlines()[0]][0]
        secs = [int(x) for x in re.findall(r"\bL(\d{5}) ", third)]
        self.assertTrue(secs and min(secs) >= 2400 and max(secs) < 3600, (min(secs), max(secs)))

    def test_a_huge_chapter_is_split_into_parts(self):
        chapters = [{"start_time": 0, "end_time": 7200, "title": "Everything"}]
        tmp, out, sections = build(*make_video(7200), meta={"title": "t", "chapters": chapters})
        self.addCleanup(tmp.cleanup)
        self.assertGreaterEqual(len(sections), 3)
        self.assertIn("**Everything (part 1/", out)
        for text in sections.values():
            self.assertLess(len(text), 40000)

    def test_stale_sections_from_a_previous_run_are_removed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        _, _, first = build(*make_video(7200), workdir=d)
        self.assertGreaterEqual(len(first), 3)
        _, out, second = build(*make_video(300), workdir=d)     # now a short video
        self.assertEqual(second, {})
        self.assertFalse((d / "sections").exists())


if __name__ == "__main__":
    unittest.main()
