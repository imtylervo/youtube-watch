"""Subtitles that are nearly empty or just [Music] tags should trigger the audio fallback."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "transcript-quality.py"


def check(lines, duration=None):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "transcript.txt"
        src.write_text("\n".join(lines), encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), str(src)]
        if duration is not None:
            cmd += ["--duration", str(duration)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, r.stdout.strip()


def talk(n, every=6):
    return [f"{i * every // 60:02d}:{i * every % 60:02d}  đây là một câu nói bình thường của người dẫn" for i in range(n)]


class TranscriptQualityTests(unittest.TestCase):
    def test_normal_speech_is_fine(self):
        rc, why = check(talk(40), duration=240)
        self.assertEqual(rc, 0, why)

    def test_nearly_empty_subtitles_for_a_long_video_are_poor(self):
        rc, why = check(["00:10  hello", "01:00  thanks", "02:30  bye", "03:00  ok", "04:00  end", "05:00  fin"], duration=600)
        self.assertEqual(rc, 1)
        self.assertIn("words/min", why)

    def test_whisper_music_only_output_is_poor(self):
        # whisper.cpp on a music-only video: *music* tags plus an invented stock phrase
        lines = ["00:00  *music*", "00:30  *music*", "00:43  *music*", "01:14  *music*", "03:12  We'll be right back."]
        rc, why = check(lines, duration=378)
        self.assertEqual(rc, 1)

    def test_mostly_music_tags_are_poor(self):
        lines = ["00:00  [Music]", "00:20  [Âm nhạc]", "00:40  [Music]", "01:00  ♪♪", "01:20  [Applause]",
                 "01:40  hello everyone welcome to the show today we talk a lot about many things"]
        rc, why = check(lines, duration=120)
        self.assertEqual(rc, 1)
        self.assertIn("[Music]", why)

    def test_short_clip_is_not_penalised_for_being_short(self):
        rc, why = check(["00:01  hello there", "00:05  second sentence here", "00:09  third", "00:12  fourth", "00:14  fifth", "00:15  sixth"],
                        duration=20)
        self.assertEqual(rc, 0, why)

    def test_duration_defaults_to_last_timestamp(self):
        sparse = ["00:10  hi", "10:00  bye", "20:00  end", "25:00  a", "28:00  b", "30:00  c"]
        rc, _ = check(sparse)  # no --duration: 30 minutes from the last line
        self.assertEqual(rc, 1)

    def test_placeholder_transcript_is_poor(self):
        rc, _ = check(["(no transcript available)"], duration=300)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
