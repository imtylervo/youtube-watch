"""sheets/: every frame, 16 per picture, so a whole video is looked at, not just ~20 frames."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make-sheets.py"
BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build-understanding.py"


def mmss(sec):
    return f"{sec // 60:02d}:{sec % 60:02d}"


def workdir(n, every=10):
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name)
    (d / "frames").mkdir()
    rows = []
    for i in range(n):
        color = f"0x{(i * 37) % 256:02x}{(i * 91) % 256:02x}{(i * 53) % 256:02x}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c={color}:s=640x360", "-frames:v", "1",
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


class SheetsTests(unittest.TestCase):
    def test_every_frame_lands_on_a_sheet(self):
        tmp, d = workdir(35)
        self.addCleanup(tmp.cleanup)
        r = run(d)
        self.assertEqual(r.returncode, 0, r.stderr)
        index = (d / "sheets" / "index.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual([l.split("\t")[0] for l in index], ["sheet_01.jpg", "sheet_02.jpg", "sheet_03.jpg"])
        self.assertEqual([l.split("\t")[1] for l in index], ["0001-0016", "0017-0032", "0033-0035"])
        times = [t for l in index for t in l.split("\t")[2].split()]
        self.assertEqual(times, [mmss(i * 10) for i in range(35)])
        self.assertEqual(size(d / "sheets" / "sheet_01.jpg"), (2560, 1440))
        self.assertEqual(size(d / "sheets" / "sheet_03.jpg"), (2560, 360))
        self.assertIn("35/35 frames", r.stderr)

    def test_pillow_labels_land_in_each_cell(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        import importlib.util
        spec = importlib.util.spec_from_file_location("sheets", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sheet.jpg"
            Image.new("RGB", (mod.CELL_W * 4, mod.CELL_H), (255, 255, 255)).save(out)
            self.assertTrue(mod.stamp(out, [("frame_0001.jpg", "00:00"), ("frame_0002.jpg", "00:10")]))
            img = Image.open(out)
            for col in (0, 1):  # a dark label box in the corner of each labelled cell
                self.assertLess(sum(img.getpixel((col * mod.CELL_W + 8, 25))), 120)
            self.assertGreater(sum(img.getpixel((2 * mod.CELL_W + 8, 25))), 600)  # unlabelled cell

    def test_no_frames_means_no_sheets(self):
        tmp, d = workdir(0)
        self.addCleanup(tmp.cleanup)
        self.assertEqual(run(d).returncode, 0)
        self.assertFalse((d / "sheets").exists())

    def test_a_previous_runs_sheets_are_removed(self):
        tmp, d = workdir(3)
        self.addCleanup(tmp.cleanup)
        (d / "sheets").mkdir()
        (d / "sheets" / "sheet_09.jpg").write_bytes(b"old")
        run(d)
        self.assertFalse((d / "sheets" / "sheet_09.jpg").exists())
        self.assertTrue((d / "sheets" / "sheet_01.jpg").exists())

    def test_understanding_tells_the_reader_to_open_every_sheet(self):
        tmp, d = workdir(20)
        self.addCleanup(tmp.cleanup)
        run(d)
        (d / "transcript.txt").write_text("00:00 hello\n", encoding="utf-8")
        header = d / "header.md"
        header.write_text("# Video Understanding\n", encoding="utf-8")
        out = subprocess.run([sys.executable, str(BUILD), str(d), "--header", str(header)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("## Frame sheets (every frame)", out.stdout)
        self.assertIn("all 20 frames in 2 pictures", out.stdout)
        self.assertIn("open EVERY sheet", out.stdout)
        self.assertIn("`sheets/sheet_02.jpg`: frames 0017-0020, 02:40–03:10", out.stdout)


if __name__ == "__main__":
    unittest.main()
