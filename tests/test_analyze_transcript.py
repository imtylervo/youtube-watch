"""Vietnamese visual cues must drive the frame plan, not fall back to talking-head."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze-transcript.py"

VI_BLOCK = [
    (5, "chào các bạn, hôm nay mình sẽ làm một bài demo"),
    (20, "các bạn thấy đoạn code này chưa"),
    (35, "bây giờ mình mở terminal lên"),
    (50, "gõ lệnh npm install để cài thư viện"),
    (70, "sau đó chạy lệnh npm start"),
    (90, "bấm vào nút Run ở góc trên"),
    (110, "nhìn vào đây, đây là sơ đồ kiến trúc của hệ thống"),
    (130, "mình sẽ cho các bạn xem kết quả"),
]
# Several blocks, like a real video, so the cue counts are realistic.
VI_LINES = [
    f"{(off + s) // 60:02d}:{(off + s) % 60:02d}  {t}"
    for off in (0, 300, 600) for s, t in VI_BLOCK
]


class AnalyzeVietnameseTests(unittest.TestCase):
    def plan_for(self, lines, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "transcript.txt"
            out = Path(tmp) / "plan.json"
            src.write_text("\n".join(lines), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(SCRIPT), str(src), "--out", str(out), *extra],
                check=True, capture_output=True,
            )
            return json.loads(out.read_text(encoding="utf-8"))

    def test_vietnamese_cues_produce_key_moments(self):
        plan = self.plan_for(VI_LINES)
        self.assertGreaterEqual(plan["key_moments_count"], 6)

    def test_vietnamese_screen_video_is_not_talking_head(self):
        plan = self.plan_for(VI_LINES)
        self.assertNotEqual(plan["video_type"], "talking-head")

    def test_short_screen_tutorial_with_few_cues_is_not_talking_head(self):
        # Real numbers from a 4-minute "install VS Code" video once its rolling
        # captions were de-duplicated: only ~6 cue phrases in the whole video.
        plan = self.plan_for([
            "00:06  chào mừng các bạn",
            "00:40  mình sẽ gõ lệnh vào đây",
            "01:05  các bạn thấy nút download này",
            "01:30  chạy lệnh cài đặt",
            "02:10  viết code đầu tiên",
            "02:50  chạy thử xem sao",
            "03:20  mình sẽ chạy lệnh cuối cùng",
            "04:00  cảm ơn các bạn đã xem",
        ])
        self.assertNotEqual(plan["video_type"], "talking-head")

    def test_an_vao_is_recognised_as_a_click(self):
        # "ấn vào" is how many Vietnamese tutorial makers say "click".
        plan = self.plan_for([
            "00:20  đó thì mình ấn vào cái lựa chọn đầu tiên",
            "00:50  thì bạn ấn vào tải phần này",
            "01:30  sau khi các bạn ấn nút next",
            "02:10  rồi tiếp tục chọn vào install",
        ])
        self.assertGreaterEqual(plan["key_moments_count"], 4)
        self.assertNotEqual(plan["video_type"], "talking-head")

    def test_long_english_podcast_with_incidental_phrases_stays_talking_head(self):
        # "now we", "moving on", "architecture" are everyday speech, not screen cues.
        lines = [f"{m:02d}:00  so anyway that is the story" for m in range(1, 60, 4)]
        lines += ["02:00  now we talk about money", "15:00  moving on to the guest",
                  "30:00  now let's go deeper", "44:00  the architecture of the bank system",
                  "50:00  now we wrap up"]
        plan = self.plan_for(lines)
        self.assertEqual(plan["video_type"], "talking-head")

    def test_everyday_vietnamese_speech_stays_talking_head(self):
        plan = self.plan_for([
            "00:30  chuyển qua chủ đề khác nhé",
            "02:00  bây giờ mình nói về gia đình",
            "04:00  sang phần tiếp theo",
            "06:00  mình viết bài này lâu rồi",
            "08:00  mình chạy bộ mỗi sáng",
            "09:30  kiến trúc sư nhà mình rất giỏi",
        ])
        self.assertEqual(plan["video_type"], "talking-head")

    def test_a_phrase_matching_two_patterns_is_counted_once(self):
        plan = self.plan_for(["00:10  now we will look at this, nhìn vào đây"])
        self.assertEqual(plan["tag_counts"].get("look-here"), 1)

    def test_plain_vietnamese_chat_stays_talking_head(self):
        plan = self.plan_for([
            "00:05  hôm nay trời đẹp quá",
            "00:30  mình ăn sáng với bạn bè",
        ])
        self.assertEqual(plan["video_type"], "talking-head")
        self.assertEqual(plan["key_moments_count"], 0)


class AnalyzeNoSpeechTests(unittest.TestCase):
    plan_for = AnalyzeVietnameseTests.plan_for

    def test_silent_video_is_sampled_over_its_real_length(self):
        # 72 s screen recording with music only: no captions, no speech.
        plan = self.plan_for(["(no transcript available)"], "--duration", "72.28")
        self.assertEqual(plan["video_type"], "no-speech")
        self.assertEqual(plan["duration_sec"], 72)
        self.assertGreaterEqual(plan["target_frame_count"], 20)
        self.assertEqual(plan["zones"][0]["start_sec"], 0)
        self.assertEqual(plan["zones"][-1]["end_sec"], 72)

    def test_real_length_wins_over_last_caption(self):
        # Speech stops at 0:30 but the video runs 2 min: plan the whole video.
        plan = self.plan_for(["00:05  hôm nay trời đẹp quá", "00:30  mình ăn sáng với bạn bè"],
                             "--duration", "120")
        self.assertEqual(plan["duration_sec"], 120)
        self.assertEqual(plan["zones"][-1]["end_sec"], 120)

    def test_unknown_length_and_no_speech_keeps_minimal_plan(self):
        plan = self.plan_for(["(no transcript available)"])
        self.assertEqual(plan["duration_sec"], 0)
        self.assertEqual(plan["zones"], [])


if __name__ == "__main__":
    unittest.main()
