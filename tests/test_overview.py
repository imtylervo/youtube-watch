"""overview.jpg: one picture of ~20 evenly spread frames, so a whole video can be grasped at a glance."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make-overview.py"
BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build-understanding.py"


def mmss(sec):
    return f"{sec // 60:02d}:{sec % 60:02d}"


def workdir(n, every=10, sizes=None):
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name)
    (d / "frames").mkdir()
    rows = []
    for i in range(n):
        w, h = (sizes[i % len(sizes)] if sizes else (640, 360))
        color = f"0x{(i * 37) % 256:02x}{(i * 91) % 256:02x}{(i * 53) % 256:02x}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c={color}:s={w}x{h}", "-frames:v", "1",
                        str(d / "frames" / f"frame_{i + 1:04d}.jpg")], check=True)
        rows.append(f"frame_{i + 1:04d}.jpg\t{mmss(i * every)}\tnormal")
    (d / "frame_index.txt").write_text("\n".join(rows), encoding="utf-8")
    return tmp, d


def run(d):
    return subprocess.run([sys.executable, str(SCRIPT), str(d)], capture_output=True, text=True)


def size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return tuple(int(x) for x in out.split("x"))


class OverviewTests(unittest.TestCase):
    def test_many_frames_give_a_5x4_sheet_of_20_evenly_spread(self):
        tmp, d = workdir(50)
        self.addCleanup(tmp.cleanup)
        r = run(d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(size(d / "overview.jpg"), (1600, 720))
        stamps = (d / "overview.txt").read_text(encoding="utf-8").split()
        self.assertEqual(len(stamps), 20)
        self.assertEqual(stamps[0], "00:00")
        self.assertEqual(stamps[-1], mmss(49 * 10))        # last frame is included
        secs = [int(s[:2]) * 60 + int(s[3:]) for s in stamps]
        self.assertEqual(secs, sorted(secs))

    def test_few_frames_use_all_of_them(self):
        tmp, d = workdir(7)
        self.addCleanup(tmp.cleanup)
        run(d)
        self.assertEqual(size(d / "overview.jpg"), (1600, 360))    # 5 columns x 2 rows
        self.assertEqual(len((d / "overview.txt").read_text(encoding="utf-8").split()), 7)

    def test_frames_of_different_sizes_are_fitted(self):
        tmp, d = workdir(6, sizes=[(1098, 720), (1280, 720), (320, 180)])
        self.addCleanup(tmp.cleanup)
        r = run(d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(size(d / "overview.jpg"), (1600, 360))

    def test_a_single_frame_is_not_worth_an_overview(self):
        tmp, d = workdir(1)
        self.addCleanup(tmp.cleanup)
        self.assertEqual(run(d).returncode, 0)
        self.assertFalse((d / "overview.jpg").exists())

    def test_no_frame_index_is_not_an_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.assertEqual(run(Path(tmp.name)).returncode, 0)

    def test_stale_overview_is_removed(self):
        tmp, d = workdir(30)
        self.addCleanup(tmp.cleanup)
        run(d)
        self.assertTrue((d / "overview.jpg").exists())
        (d / "frame_index.txt").write_text("", encoding="utf-8")
        run(d)
        self.assertFalse((d / "overview.jpg").exists())
        self.assertFalse((d / "overview.txt").exists())


class UnderstandingMentionsOverviewTests(unittest.TestCase):
    def build(self, with_overview):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "frame_index.txt").write_text("frame_0001.jpg\t00:00\tnormal", encoding="utf-8")
            (d / "transcript.txt").write_text("00:01  hello", encoding="utf-8")
            if with_overview:
                (d / "overview.jpg").write_bytes(b"x")
                (d / "overview.txt").write_text("00:00 00:31 01:02", encoding="utf-8")
            return subprocess.run([sys.executable, str(BUILD), str(d)],
                                  check=True, capture_output=True, text=True).stdout

    def test_overview_is_explained_with_its_timestamps(self):
        out = self.build(True)
        self.assertIn("overview.jpg", out)
        self.assertIn("00:00 00:31 01:02", out)
        self.assertIn("left to right", out)

    def test_nothing_is_said_without_an_overview(self):
        self.assertNotIn("overview", self.build(False).lower())


if __name__ == "__main__":
    unittest.main()
