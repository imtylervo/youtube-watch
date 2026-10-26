"""Frame extraction: scene frames are added, exact duplicates dropped, small changes kept."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract-frames-from-plan.py"

# Solid red for 5s then solid blue: a big scene change at t=5.
RED_TO_BLUE = (
    "color=c=red:s=320x180:d=10:r=10,"
    "drawbox=x=0:y=0:w=iw:h=ih:color=blue:t=fill:enable='gte(t,5)'"
)
# White page; at t=5 one thin dark line appears (like one new bullet / code line).
ONE_NEW_LINE = (
    "color=c=white:s=640x360:d=10:r=10,"
    "drawbox=x=40:y=100:w=400:h=12:color=black:t=fill:enable='gte(t,5)'"
)
# 1280x720 page; at t=5 a short 160x14 line appears (a few typed words).
SHORT_LINE = (
    "color=c=white:s=1280x720:d=10:r=10,"
    "drawbox=x=100:y=200:w=160:h=14:color=black:t=fill:enable='gte(t,5)'"
)
# Only a mouse-pointer-sized blob moves: not new information.
POINTER_ONLY = (
    "color=c=white:s=1280x720:d=10:r=10,"
    "drawbox=x=600:y=300:w=12:h=19:color=black:t=fill:enable='gte(t,5)'"
)
PLAN = {
    "video_type": "mixed", "duration_sec": 10, "target_frame_count": 5,
    "zones": [{"start_sec": 0, "end_sec": 10, "every_sec": 2, "density": "normal"}],
}


def make_video(path: Path, lavfi: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", lavfi,
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)],
        check=True,
    )


def run_extract(lavfi: str, extra=()):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    video = root / "video.mp4"
    make_video(video, lavfi)
    plan = root / "plan.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(SCRIPT), str(video), str(plan),
         "--out-dir", str(root / "frames"), *extra],
        check=True, capture_output=True,
    )
    rows = [line.split("\t") for line in
            (root / "frame_index.txt").read_text(encoding="utf-8").splitlines()]
    files = sorted(p.name for p in (root / "frames").glob("*.jpg"))
    return tmp, rows, files


def secs(mmss: str) -> int:
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


class ExtractFramesTests(unittest.TestCase):
    def test_scene_change_is_kept_and_labelled(self):
        tmp, rows, _ = run_extract(RED_TO_BLUE)
        self.addCleanup(tmp.cleanup)
        scene = [r for r in rows if r[2] == "scene"]
        self.assertTrue(scene, rows)
        self.assertTrue(4 <= secs(scene[0][1]) <= 6, scene)

    def test_identical_frames_are_dropped(self):
        tmp, rows, files = run_extract(RED_TO_BLUE)
        self.addCleanup(tmp.cleanup)
        # 5 sampled instants (0,2,4,6,8) + scene frame; each colour needs just one.
        self.assertLessEqual(len(rows), 3, rows)
        self.assertEqual(len(rows), len(files))

    def test_one_new_line_is_not_treated_as_duplicate(self):
        tmp, rows, _ = run_extract(ONE_NEW_LINE)
        self.addCleanup(tmp.cleanup)
        times = [secs(r[1]) for r in rows]
        self.assertTrue(any(t < 5 for t in times), rows)
        self.assertTrue(any(t >= 5 for t in times), rows)

    def test_short_typed_line_on_a_big_page_is_kept(self):
        tmp, rows, _ = run_extract(SHORT_LINE)
        self.addCleanup(tmp.cleanup)
        times = [secs(r[1]) for r in rows]
        self.assertTrue(any(t < 5 for t in times) and any(t >= 5 for t in times), rows)

    def test_pointer_sized_change_is_a_duplicate(self):
        tmp, rows, _ = run_extract(POINTER_ONLY)
        self.addCleanup(tmp.cleanup)
        self.assertEqual(len(rows), 1, rows)

    def test_index_files_are_sequential_and_exist(self):
        tmp, rows, files = run_extract(RED_TO_BLUE)
        self.addCleanup(tmp.cleanup)
        expected = [f"frame_{i:04d}.jpg" for i in range(1, len(rows) + 1)]
        self.assertEqual([r[0] for r in rows], expected)
        self.assertEqual(files, expected)

    def test_stale_frames_from_previous_run_are_removed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "frames").mkdir()
        (root / "frames" / "frame_0099.jpg").write_bytes(b"old")
        make_video(root / "video.mp4", RED_TO_BLUE)
        (root / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
        subprocess.run([sys.executable, str(SCRIPT), str(root / "video.mp4"),
                        str(root / "plan.json"), "--out-dir", str(root / "frames")],
                       check=True, capture_output=True)
        self.assertFalse((root / "frames" / "frame_0099.jpg").exists())

    def test_max_frames_cap_is_respected(self):
        tmp, rows, _ = run_extract(ONE_NEW_LINE, extra=["--max-frames", "1"])
        self.addCleanup(tmp.cleanup)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
