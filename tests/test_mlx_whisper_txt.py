"""mlx-whisper tier: lines made up over music are dropped; missing models never download."""
from pathlib import Path
import importlib.util
import os
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mlx-whisper-txt.py"
spec = importlib.util.spec_from_file_location("mlx_txt", SCRIPT)
mlx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mlx)


class InventedTests(unittest.TestCase):
    def test_stock_line_over_a_whole_window_is_dropped(self):
        # seen on a Vietnamese vlog: 30 s of eating music became this line
        text = "Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn"
        self.assertTrue(mlx.invented({"start": 160.8, "end": 190.8}, text))

    def test_real_speech_is_kept(self):
        text = "giờ út bày ra dĩa hấp, lóc bên dưới một lớp hành"
        self.assertFalse(mlx.invented({"start": 108.4, "end": 117.5}, text))

    def test_long_dense_speech_is_kept(self):
        self.assertFalse(mlx.invented({"start": 0, "end": 25}, " ".join(["chữ"] * 60)))


class CacheTests(unittest.TestCase):
    def test_model_counts_as_cached_only_with_snapshots(self):
        with tempfile.TemporaryDirectory() as hub:
            old = os.environ.get("HF_HUB_CACHE")
            os.environ["HF_HUB_CACHE"] = hub
            try:
                self.assertFalse(mlx.cached("mlx-community/whisper-x"))
                (Path(hub) / "models--mlx-community--whisper-x" / "snapshots").mkdir(parents=True)
                self.assertTrue(mlx.cached("mlx-community/whisper-x"))
            finally:
                if old is None:
                    os.environ.pop("HF_HUB_CACHE")
                else:
                    os.environ["HF_HUB_CACHE"] = old


if __name__ == "__main__":
    unittest.main()
