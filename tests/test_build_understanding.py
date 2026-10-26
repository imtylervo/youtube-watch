"""understanding.md becomes a timeline: each frame followed by what was said around it."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build-understanding.py"

INDEX = "frame_0001.jpg\t00:10\tnormal\nframe_0002.jpg\t00:40\tscene\nframe_0003.jpg\t125:00\tdense"
TRANSCRIPT = "\n".join([
    "00:02  intro before first frame",
    "00:12  explaining the setup",
    "00:39  just before the scene change",
    "00:41  now the new slide",
    "02:05:01  very late line",
])


def build(index=INDEX, transcript=TRANSCRIPT, ocr=None, header="# Header\n"):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "frame_index.txt").write_text(index, encoding="utf-8")
        (d / "transcript.txt").write_text(transcript, encoding="utf-8")
        (d / "header.md").write_text(header, encoding="utf-8")
        if ocr is not None:
            (d / "ocr.tsv").write_text(ocr, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPT), str(d), "--header", str(d / "header.md")],
            check=True, capture_output=True, text=True,
        )
        return r.stdout


class BuildUnderstandingTests(unittest.TestCase):
    def test_header_comes_first(self):
        self.assertTrue(build().startswith("# Header"))

    def test_lines_sit_under_the_right_frame(self):
        out = build()
        sections = out.split("### ")[1:]
        self.assertEqual(len(sections), 3)
        self.assertIn("intro before first frame", sections[0])   # before frame 1 -> frame 1
        self.assertIn("explaining the setup", sections[0])
        self.assertIn("just before the scene change", sections[0])
        self.assertIn("now the new slide", sections[1])
        self.assertIn("very late line", sections[2])

    def test_no_transcript_line_is_lost(self):
        out = build()
        for line in TRANSCRIPT.splitlines():
            self.assertIn(line.split("  ", 1)[1], out)

    def test_section_title_has_time_frame_and_label(self):
        out = build()
        self.assertIn("### [00:40] frame_0002.jpg (scene)", out)
        self.assertIn("### [125:00] frame_0003.jpg (dense)", out)

    def test_ocr_text_is_shown_when_present(self):
        out = build(ocr="frame_0002.jpg\tdef main(): print('hello world')")
        self.assertIn("> OCR: def main(): print('hello world')", out)

    def test_no_ocr_section_without_ocr_file(self):
        self.assertNotIn("OCR", build())

    def test_transcript_without_frames_is_still_output(self):
        out = build(index="")
        self.assertIn("explaining the setup", out)


if __name__ == "__main__":
    unittest.main()
