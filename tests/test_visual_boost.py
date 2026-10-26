"""A video whose picture keeps changing must be sampled at a steady cadence even when
the transcript gave no visual cues (language-independent; based only on scene changes)."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract-frames-from-plan.py"
spec = importlib.util.spec_from_file_location("efp", SCRIPT)
efp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(efp)

TALKING_HEAD = [
    {"start_sec": 0, "end_sec": 300, "every_sec": 30, "density": "normal"},
    {"start_sec": 300, "end_sec": 320, "every_sec": 10, "density": "dense"},
    {"start_sec": 320, "end_sec": 600, "every_sec": 30, "density": "normal"},
]


class BoostTests(unittest.TestCase):
    def test_many_scene_changes_tighten_normal_zones(self):
        scenes = list(range(10, 600, 20))            # ~3 changes a minute
        zones = efp.boost_for_visual(TALKING_HEAD, scenes, 600)
        self.assertEqual([z["every_sec"] for z in zones], [10, 10, 10])
        self.assertEqual(zones[1]["density"], "dense")

    def test_few_scene_changes_leave_the_plan_alone(self):
        zones = efp.boost_for_visual(TALKING_HEAD, [100, 400], 600)   # 0.2 a minute
        self.assertEqual(zones, TALKING_HEAD)

    def test_one_camera_flicker_burst_counts_once(self):
        scenes = [50, 51, 52, 53, 54, 55]            # a single burst, not six changes
        zones = efp.boost_for_visual(TALKING_HEAD, scenes, 600)
        self.assertEqual(zones, TALKING_HEAD)

    def test_already_dense_zones_are_never_loosened(self):
        plan = [{"start_sec": 0, "end_sec": 100, "every_sec": 6, "density": "normal"}]
        zones = efp.boost_for_visual(plan, list(range(5, 100, 10)), 100)
        self.assertEqual(zones[0]["every_sec"], 6)

    def test_unknown_duration_changes_nothing(self):
        self.assertEqual(efp.boost_for_visual(TALKING_HEAD, list(range(0, 600, 5)), 0), TALKING_HEAD)

    def test_input_plan_is_not_mutated(self):
        before = json.dumps(TALKING_HEAD)
        efp.boost_for_visual(TALKING_HEAD, list(range(10, 600, 20)), 600)
        self.assertEqual(json.dumps(TALKING_HEAD), before)


def run_log(lavfi, duration):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", lavfi,
                        "-pix_fmt", "yuv420p", "-c:v", "libx264", str(root / "v.mp4")], check=True)
        plan = {"video_type": "talking-head", "duration_sec": duration, "target_frame_count": 3,
                "zones": [{"start_sec": 0, "end_sec": duration, "every_sec": 30, "density": "normal"}]}
        (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), str(root / "v.mp4"), str(root / "plan.json"),
                            "--out-dir", str(root / "frames")], capture_output=True, text=True, check=True)
        return r.stderr


class EndToEndTests(unittest.TestCase):
    def test_flip_flopping_video_is_reported_as_visual_heavy(self):
        flip = ("color=c=red:s=320x180:d=90:r=5,"
                "drawbox=x=0:y=0:w=iw:h=ih:color=blue:t=fill:enable='lt(mod(t,10),5)'")
        self.assertIn("visual-heavy", run_log(flip, 90))

    def test_static_video_is_not(self):
        self.assertNotIn("visual-heavy", run_log("color=c=gray:s=320x180:d=90:r=5", 90))


if __name__ == "__main__":
    unittest.main()
