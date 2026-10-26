#!/usr/bin/env python3
"""Decide whether subtitles are good enough to trust, or the audio should be transcribed.

Exit 0 = fine. Exit 1 = unreliable; the reason is printed on stdout.
Unreliable means: no caption lines at all, more than half the lines are only
tags like [Music] / [Âm nhạc] / *music* / ♪, or (for videos of a minute or more) fewer than
15 spoken words per minute.

Usage: transcript-quality.py <transcript.txt> [--duration SECONDS]
       (duration defaults to the last timestamp in the file)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MIN_WORDS_PER_MIN = 15
MAX_TAG_SHARE = 0.5
LINE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})\s+(.*)$")
TAG_ONLY = re.compile(r"^(?:[\[\(][^\]\)]*[\]\)]|\*[^*]*\*|[♪♫\s]+)$")  # [Music] (Music) *music* ♪


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("transcript")
    p.add_argument("--duration", type=float, default=0)
    args = p.parse_args()

    entries: list[tuple[int, str]] = []
    for raw in Path(args.transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(raw.strip())
        if m:
            ts = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            entries.append((ts, m.group(4).strip()))
    if not entries:
        print("no caption lines")
        return 1

    tags = [t for _, t in entries if TAG_ONLY.match(t)]
    if len(tags) / len(entries) > MAX_TAG_SHARE:
        print(f"{len(tags) * 100 // len(entries)}% of lines are only tags like [Music]")
        return 1

    duration = args.duration or max(ts for ts, _ in entries)
    if duration >= 60:
        words = sum(len(t.split()) for _, t in entries if not TAG_ONLY.match(t))
        per_min = words / (duration / 60)
        if per_min < MIN_WORDS_PER_MIN:
            print(f"only {per_min:.0f} words/min (under {MIN_WORDS_PER_MIN})")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
