"""faster-whisper tier: timestamps match the other tiers; wrong WAV formats are refused."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
import wave

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "faster-whisper-txt.py"
spec = importlib.util.spec_from_file_location("fw_txt", SCRIPT)
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)


def write_wav(path, rate=16000, channels=1, frames=1600):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * frames)


class Stamp(unittest.TestCase):
    def test_short_audio_uses_mm_ss(self):
        self.assertEqual(fw.stamp(65.9, long=False), "01:05")

    def test_long_audio_uses_hh_mm_ss(self):
        self.assertEqual(fw.stamp(3725, long=True), "01:02:05")


class ReadWav(unittest.TestCase):
    def test_reads_16k_mono(self):
        with tempfile.TemporaryDirectory() as d:
            write_wav(Path(d) / "a.wav")
            self.assertEqual(len(fw.read_wav(str(Path(d) / "a.wav"))), 1600)

    def test_refuses_stereo(self):
        with tempfile.TemporaryDirectory() as d:
            write_wav(Path(d) / "a.wav", channels=2)
            with self.assertRaises(SystemExit):
                fw.read_wav(str(Path(d) / "a.wav"))


if __name__ == "__main__":
    unittest.main()
