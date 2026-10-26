"""A local video file works end to end: frames come from the file, and the file survives cleanup."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract-v3.sh"


class LocalFileTests(unittest.TestCase):
    def test_local_mp4_gives_frames_and_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "my clip.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
                            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "20", "-shortest", str(src)], check=True)
            out = Path(tmp) / "out"
            r = subprocess.run(["bash", str(SCRIPT), str(src), "--no-whisper", "--out", str(out)],
                               capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, YOUTUBE_WATCH_PYTHON=os.environ.get("PYTHON", "python3")))
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertTrue(src.exists(), "the user's file must not be deleted")
            self.assertGreater(len(list((out / "frames").glob("frame_*.jpg"))), 0)
            self.assertIn("my clip.mp4", (out / "understanding.md").read_text())
            self.assertNotIn("is not a valid URL", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
