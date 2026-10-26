"""YouTube auto-captions roll: each cue repeats the previous line. Emit every line once."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vtt-to-txt.py"

ROLLING = """WEBVTT
Kind: captions
Language: vi

00:00:05.000 --> 00:00:07.000 align:start position:0%
Chào mừng các bạn<00:00:06.000><c> tới</c>

00:00:07.000 --> 00:00:07.010 align:start position:0%
Chào mừng các bạn tới

00:00:07.010 --> 00:00:09.000 align:start position:0%
Chào mừng các bạn tới
viên 24 gi thì hôm nay<00:00:08.000><c> mình</c>

00:00:09.000 --> 00:00:09.010 align:start position:0%
viên 24 gi thì hôm nay mình

00:00:09.010 --> 00:00:11.000 align:start position:0%
viên 24 gi thì hôm nay mình
sẽ hướng dẫn cài VS code
"""


def convert(vtt: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "t.vtt"
        src.write_text(vtt, encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), str(src)],
                           check=True, capture_output=True, text=True)
        return r.stdout.splitlines()


class VttToTxtTests(unittest.TestCase):
    def test_rolling_captions_are_emitted_once_each(self):
        self.assertEqual(convert(ROLLING), [
            "00:05  Chào mừng các bạn tới",
            "00:07  viên 24 gi thì hôm nay mình",
            "00:09  sẽ hướng dẫn cài VS code",
        ])

    def test_manual_subtitles_keep_every_line(self):
        vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello there\n\n"
               "00:00:03.000 --> 00:00:04.000\nSecond sentence\n\n"
               "00:00:05.000 --> 00:00:06.000\nHello there\n")
        self.assertEqual(convert(vtt), [
            "00:01  Hello there", "00:03  Second sentence", "00:05  Hello there"])

    def test_hours_use_hh_mm_ss(self):
        vtt = "WEBVTT\n\n01:02:03.000 --> 01:02:05.000\nLate line\n"
        self.assertEqual(convert(vtt), ["01:02:03  Late line"])

    def test_markup_and_entities_are_stripped(self):
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<c.colorE5E5E5>a &amp; b</c> &gt;&gt; c\n"
        self.assertEqual(convert(vtt), ["00:01  a & b >> c"])


if __name__ == "__main__":
    unittest.main()
