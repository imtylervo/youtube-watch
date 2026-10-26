#!/usr/bin/env python3
"""Analyze a transcript file → output a frame extraction plan as JSON.

Reads a transcript with "MM:SS  text" or "HH:MM:SS  text" lines (or plain
text without timestamps) and produces a plan describing:
  - video_type: tutorial-code / slide-presentation / talking-head /
                demo-ui / live-coding / livestream-chat / vlog / mixed
  - duration_sec: the real length (--duration) when known, else the last timestamp
  - key_moments: list of {ts_sec, reason} where the speaker references
                  visuals ("look at this", "next slide", "see here", ...)
  - zones: list of {start_sec, end_sec, density} for the planner —
           density "dense" (1 frame / 2s), "normal" (1 frame / 8s),
           "sparse" (1 frame / 30s)
  - target_frame_count: rough budget — sum of zones × densities

Usage:
  analyze-transcript.py <transcript.txt> [--out plan.json] [--max-frames N]
                        [--duration SEC]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

# Regex patterns for visual cues in transcript
KEY_PHRASES = {
    "look-here":      [r"\b(look at this|look here|see this|see here|notice (this|the))\b",
                       r"\b(nhìn vào (đây|màn hình|slide)|các bạn thấy|như các bạn thấy|bạn thấy (đây|đấy)|chú ý (đây|vào))\b"],
    "next-slide":     [r"\b(next slide|moving on|let's (look at|move to)|now (let's|we))\b",
                       r"\b(slide (tiếp|kế tiếp|tiếp theo)|sang (slide|bước)|tiếp theo (là|chúng ta))\b"],
    "code-action":    [r"\b(let me (write|type|code|run)|let's (run|type|code)|run this command|type this)\b",
                       r"\b(gõ lệnh|chạy lệnh|viết code|chạy thử)\b"],
    "click-action":   [r"\b(click (here|on|this)|press (this|that)|tap (here|on)|select (this|the))\b",
                       r"\b(bấm vào|(ấn|nhấn) (vào|nút|lên)|click vào|chọn vào|nhấp (vào|chuột))\b"],
    "screen-share":   [r"\b(open (vs ?code|terminal|browser|cursor)|share my screen|switch (to|over))\b",
                       r"\b(mở (vs ?code|terminal|trình duyệt|cursor)|chia sẻ màn hình)\b"],
    "diagram":        [r"\b(this diagram|the diagram|architecture|the chart|this graph)\b",
                       r"\b(sơ đồ|biểu đồ|đồ thị)\b"],
    "demo":           [r"\b(let me (show|demo)|live demo|let's see (this|how)|here's how)\b",
                       r"\b((để )?mình (sẽ )?(demo|cho (các )?bạn xem)|demo (luôn|thử)|cho các bạn xem)\b"],
}

# Video-type heuristics: which key-phrase categories fire most
TYPE_FROM_PHRASES = [
    ("tutorial-code",       {"code-action", "screen-share"}, 0.30),
    ("demo-ui",             {"click-action", "screen-share"}, 0.25),
    ("slide-presentation",  {"next-slide", "look-here"}, 0.25),
    ("livestream-chat",     {"chat", "comment", "viewer"}, 0.0),  # rule below
]


NO_TRANSCRIPT = "(no transcript available)"  # placeholder written by extract-v3.sh


def parse_transcript(text: str, duration_sec: int = 0) -> list[tuple[int, str]]:
    """Return list of (ts_sec, text). If no timestamps, generate evenly.

    Accepts:
      "MM:SS  text"        e.g. "23:45  hello"
      "HH:MM:SS  text"     e.g. "01:23:45  hello"
      Plain "text"         (no ts — assigned 0, later evenly distributed)
    """
    out: list[tuple[int, str]] = []
    last_ts = 0
    has_ts = False
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.strip() == NO_TRANSCRIPT:
            continue
        m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})\s+(.+)$", line)
        if m:
            h, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
            ts = h * 3600 + mm * 60 + ss
            out.append((ts, m.group(4)))
            last_ts = ts
            has_ts = True
            continue
        m = re.match(r"^(\d{1,2}):(\d{2})\s+(.+)$", line)
        if m:
            ts = int(m.group(1)) * 60 + int(m.group(2))
            out.append((ts, m.group(3)))
            last_ts = ts
            has_ts = True
            continue
        # plain text — append with last_ts
        out.append((last_ts, line.strip()))
    # If no timestamps found, distribute evenly across the video (or an estimated 30 min)
    if not has_ts and out:
        n = len(out)
        span = duration_sec or 1800
        sys.stderr.write(f"⚠ no timestamps in transcript — distributing {n} lines evenly over {span}s\n")
        for i in range(n):
            ts = int(i * span / n)
            out[i] = (ts, out[i][1])
    return out


def find_key_moments(lines: list[tuple[int, str]]) -> tuple[list[dict], Counter]:
    """Scan transcript for visual cues → list of key timestamps + tag counter."""
    moments = []
    tag_counts: Counter = Counter()
    seen_ts = set()
    for ts, text in lines:
        # NFC so Vietnamese diacritics match whether the source composed them or not.
        text_lower = unicodedata.normalize("NFC", text).lower()
        for tag, patterns in KEY_PHRASES.items():
            for pat in patterns:
                if re.search(pat, text_lower):
                    tag_counts[tag] += 1
                    # Dedupe: don't add the same exact ts twice
                    key = (ts // 5, tag)  # cluster within 5s
                    if key not in seen_ts:
                        moments.append({"ts_sec": ts, "tag": tag, "text": text[:100]})
                        seen_ts.add(key)
                    break  # one hit per tag per line, whichever language matched
    return moments, tag_counts


def classify_video(lines: list[tuple[int, str]], tag_counts: Counter, total_lines: int,
                   duration_sec: int = 0) -> str:
    """Heuristic: pick the dominant video type."""
    # Livestream chat detection: many @mentions or "chat says" / "@viewer"
    chat_lines = sum(1 for _, t in lines if "@" in t or "chat says" in t.lower())
    if chat_lines > total_lines * 0.10:
        return "livestream-chat"

    if not tag_counts:
        return "talking-head"  # no visual cues — likely podcast/interview

    # Tutorial-code: code/screen-share dominant
    code_score = tag_counts.get("code-action", 0) + tag_counts.get("screen-share", 0)
    click_score = tag_counts.get("click-action", 0) + tag_counts.get("screen-share", 0)
    slide_score = tag_counts.get("next-slide", 0) + tag_counts.get("look-here", 0)
    diagram_score = tag_counts.get("diagram", 0)

    scores = {
        "tutorial-code": code_score,
        "demo-ui": click_score,
        "slide-presentation": slide_score + diagram_score,
    }
    best = max(scores, key=scores.get)
    if scores[best] > 5:
        return best
    # A short screen tutorial only says "type this" a handful of times, but says it
    # often for its length. Everyday phrases ("now we", "moving on") are far sparser.
    minutes = max(1.0, duration_sec / 60)
    if scores[best] >= 3 and scores[best] / minutes >= 0.7:
        return best
    return "talking-head"


def plan_zones(duration_sec: int, video_type: str, key_moments: list[dict],
               max_frames: int = 300) -> list[dict]:
    """Produce a list of zones that the extractor will sample at different
    densities. Density is captured as `every_sec` — 1 frame every N seconds.
    """
    # Density profiles per video type (every_sec)
    profile = {
        "tutorial-code":      {"normal_every": 8,  "dense_every": 2,  "sparse_every": 30},
        "demo-ui":            {"normal_every": 6,  "dense_every": 2,  "sparse_every": 30},
        "slide-presentation": {"normal_every": 10, "dense_every": 3,  "sparse_every": 60},
        "livestream-chat":    {"normal_every": 15, "dense_every": 4,  "sparse_every": 60},
        "talking-head":       {"normal_every": 30, "dense_every": 10, "sparse_every": 120},
        "vlog":               {"normal_every": 12, "dense_every": 4,  "sparse_every": 45},
        "mixed":              {"normal_every": 12, "dense_every": 3,  "sparse_every": 45},
        # No speech: the picture is all there is, so sample it closely.
        "no-speech":          {"normal_every": 3,  "dense_every": 3,  "sparse_every": 10},
    }.get(video_type, {"normal_every": 12, "dense_every": 3, "sparse_every": 45})

    # Build dense windows around key moments (±10s)
    DENSE_WINDOW = 10
    dense_starts = sorted({max(0, m["ts_sec"] - DENSE_WINDOW) for m in key_moments})
    dense_ranges = []  # list of (start, end)
    for ds in dense_starts:
        de = ds + 2 * DENSE_WINDOW
        if dense_ranges and ds <= dense_ranges[-1][1]:
            # Merge overlapping
            dense_ranges[-1] = (dense_ranges[-1][0], max(dense_ranges[-1][1], de))
        else:
            dense_ranges.append((ds, de))

    # Build zone list: alternate normal / dense
    zones = []
    cursor = 0
    for ds, de in dense_ranges:
        if cursor < ds:
            zones.append({"start_sec": cursor, "end_sec": ds,
                          "every_sec": profile["normal_every"], "density": "normal"})
        zones.append({"start_sec": ds, "end_sec": min(de, duration_sec),
                      "every_sec": profile["dense_every"], "density": "dense"})
        cursor = min(de, duration_sec)
    if cursor < duration_sec:
        zones.append({"start_sec": cursor, "end_sec": duration_sec,
                      "every_sec": profile["normal_every"], "density": "normal"})

    # Calculate frame budget — clamp if too many
    total_frames = sum(max(1, (z["end_sec"] - z["start_sec"]) // z["every_sec"]) for z in zones)
    if total_frames > max_frames:
        # Scale all every_sec uniformly to fit budget
        scale = total_frames / max_frames
        for z in zones:
            z["every_sec"] = max(1, int(z["every_sec"] * scale))
        total_frames = sum(max(1, (z["end_sec"] - z["start_sec"]) // z["every_sec"]) for z in zones)

    return zones, total_frames


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("transcript", help="Path to transcript.txt")
    p.add_argument("--out", default="-", help="Path to output plan JSON (default: stdout)")
    p.add_argument("--max-frames", type=int, default=300)
    p.add_argument("--duration", type=float, default=0,
                   help="real video length in seconds (0 = unknown, use the transcript)")
    args = p.parse_args()
    real_duration = int(args.duration)

    text = Path(args.transcript).read_text(encoding="utf-8", errors="replace")
    lines = parse_transcript(text, real_duration)
    if not lines and real_duration > 0:
        sys.stderr.write("⚠ no speech — sampling the whole video evenly\n")
        zones, total_frames = plan_zones(real_duration, "no-speech", [], args.max_frames)
        plan = {"video_type": "no-speech", "duration_sec": real_duration,
                "transcript_lines": 0, "key_moments_count": 0, "key_moments": [],
                "tag_counts": {}, "target_frame_count": total_frames, "zones": zones}
    elif not lines:
        sys.stderr.write("⚠ empty transcript — emit minimal plan (talking-head, sparse)\n")
        plan = {"video_type": "talking-head", "duration_sec": 0,
                "key_moments": [], "zones": [], "target_frame_count": 0}
    else:
        duration = max(real_duration, max(ts for ts, _ in lines))
        moments, tag_counts = find_key_moments(lines)
        video_type = classify_video(lines, tag_counts, len(lines), duration)
        zones, total_frames = plan_zones(duration, video_type, moments, args.max_frames)
        plan = {
            "video_type": video_type,
            "duration_sec": duration,
            "transcript_lines": len(lines),
            "key_moments_count": len(moments),
            "key_moments": moments[:50],  # cap for plan readability
            "tag_counts": dict(tag_counts),
            "target_frame_count": total_frames,
            "zones": zones,
        }

    output = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out == "-":
        print(output)
    else:
        Path(args.out).write_text(output, encoding="utf-8")
        sys.stderr.write(f"→ plan saved to {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
