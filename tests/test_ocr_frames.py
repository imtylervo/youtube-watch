"""--ocr is optional: without tesseract it must warn and carry on, never fail the run."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ocr-frames.py"

FAKE_TESSERACT = """#!/bin/sh
# canned OCR text lives in $FAKE_DIR/<image basename>.txt
if [ "$1" = "--list-langs" ]; then printf 'List of available languages (2):\\neng\\nvie\\n'; exit 0; fi
cat "$FAKE_DIR/$(basename "$1").txt" 2>/dev/null
"""


def workdir():
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name)
    (d / "frames").mkdir()
    for n in ("frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"):
        (d / "frames" / n).write_bytes(b"x")
    (d / "frame_index.txt").write_text(
        "frame_0001.jpg\t00:01\tnormal\nframe_0002.jpg\t00:02\tnormal\nframe_0003.jpg\t00:03\tscene",
        encoding="utf-8")
    return tmp, d


def run(d, path_dirs, fake_dir=""):
    env = dict(os.environ, PATH=os.pathsep.join(path_dirs), FAKE_DIR=fake_dir)
    return subprocess.run([sys.executable, str(SCRIPT), str(d)],
                          capture_output=True, text=True, env=env)


class OcrFramesTests(unittest.TestCase):
    def test_missing_tesseract_warns_and_succeeds(self):
        tmp, d = workdir()
        self.addCleanup(tmp.cleanup)
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        r = run(d, [empty.name])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("brew install tesseract", r.stderr)
        self.assertFalse((d / "ocr.tsv").exists())

    def fake_run(self, texts, frames=("frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg")):
        tmp, d = workdir()
        self.addCleanup(tmp.cleanup)
        (d / "frame_index.txt").write_text(
            "\n".join(f"{n}\t00:0{i}\tnormal" for i, n in enumerate(frames, 1)), encoding="utf-8")
        for n in frames:
            (d / "frames" / n).write_bytes(b"x")
        bindir = tempfile.TemporaryDirectory()
        self.addCleanup(bindir.cleanup)
        fake = Path(bindir.name) / "tesseract"
        fake.write_text(FAKE_TESSERACT)
        fake.chmod(0o755)
        canned = Path(bindir.name) / "canned"
        canned.mkdir()
        for name, text in texts.items():
            (canned / f"{name}.txt").write_text(text, encoding="utf-8")
        r = run(d, [bindir.name, "/bin", "/usr/bin"], str(canned))
        rows = []
        if (d / "ocr.tsv").exists():
            rows = [x.split("\t") for x in (d / "ocr.tsv").read_text(encoding="utf-8").splitlines()]
        return r, rows

    def test_keeps_only_substantial_text_on_one_line(self):
        r, rows = self.fake_run({"frame_0001.jpg": 'def main():\n    print("hello world")\n',
                                 "frame_0002.jpg": "ok\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rows, [["frame_0001.jpg", 'def main(): print("hello world")']])

    def test_long_text_is_truncated(self):
        r, rows = self.fake_run({"frame_0001.jpg": "word " * 400})
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0][1]), 301)
        self.assertTrue(rows[0][1].endswith("…"))

    def test_text_identical_to_previous_frame_is_skipped(self):
        same = "the very same slide text on both frames"
        r, rows = self.fake_run({"frame_0001.jpg": same, "frame_0002.jpg": same,
                                 "frame_0003.jpg": "a different slide with new words"})
        self.assertEqual([x[0] for x in rows], ["frame_0001.jpg", "frame_0003.jpg"])

    def test_missing_frame_index_does_not_crash(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bindir = tempfile.TemporaryDirectory()
        self.addCleanup(bindir.cleanup)
        fake = Path(bindir.name) / "tesseract"
        fake.write_text(FAKE_TESSERACT)
        fake.chmod(0o755)
        r = run(Path(tmp.name), [bindir.name, "/bin", "/usr/bin"])
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
