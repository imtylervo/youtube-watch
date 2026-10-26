"""A picture that fades into the next one is a scene change, although ffmpeg's scene
score (neighbouring frames) never rises; a camera that keeps moving is not."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract-frames-from-plan.py"
spec = importlib.util.spec_from_file_location("efp", SCRIPT)
efp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(efp)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


class GradualChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        # Two different stills (a dark title card, then a bright chart-like card), 2 s fade.
        ffmpeg("-f", "lavfi", "-i", "color=c=0x101020:s=640x360:d=6,drawbox=x=80:y=60:w=480:h=40:color=white:t=fill",
               "-f", "lavfi", "-i", "testsrc2=s=640x360:d=6,hue=s=0",
               "-filter_complex", "[0][1]xfade=transition=fade:duration=2:offset=4,format=yuv420p",
               "-r", "25", str(d / "fade.mp4"))
        # One still, panned slowly the whole time (a moving camera, no new picture).
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1280x720:d=10,hue=s=0",
               "-vf", "crop=640:360:x='t*40':y='t*20',format=yuv420p", "-r", "25", str(d / "pan.mp4"))
        cls.dir = d

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_fade_is_one_gradual_change(self):
        cuts, gradual = efp.scene_timestamps(self.dir / "fade.mp4", 0.3)
        self.assertEqual(cuts, [], "ffmpeg's scene score should miss a 2 s fade")
        self.assertEqual(len(gradual), 1, gradual)
        self.assertTrue(4 <= gradual[0] <= 7, gradual)

    def test_slow_pan_is_not_a_change(self):
        _, gradual = efp.scene_timestamps(self.dir / "pan.mp4", 0.3)
        self.assertEqual(gradual, [])

    def test_held_picture_after_change_only(self):
        a, b = bytes([0]) * 100, bytes([200]) * 100
        # 2 fps: a for 3 s, then b for 3 s (a cut that holds) -> one change at the cut
        self.assertEqual(efp.gradual_changes([a] * 6 + [b] * 6), [3])
        # every sample different from the last (a moving camera) -> never holds
        self.assertEqual(efp.gradual_changes([bytes([k * 20]) * 100 for k in range(12)]), [])


if __name__ == "__main__":
    unittest.main()
