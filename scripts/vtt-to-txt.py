#!/usr/bin/env python3
"""Convert a WebVTT subtitle file to "MM:SS  text" lines on stdout.

YouTube auto-captions "roll": every cue repeats the previous line and adds a new
one, so a naive conversion prints each sentence two or three times. Here each
line is emitted once, stamped with the start of the cue where it first appeared.
A line is skipped only if it equals the line emitted just before it (the only
one a rolling cue repeats), so a phrase that genuinely comes back later is kept.

Usage: vtt-to-txt.py <file.vtt>
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path


def stamp(start: str) -> str:
    h, m, s = start.split(".")[0].split(":")
    return f"{int(m):02d}:{s}" if int(h) == 0 else f"{int(h):02d}:{m}:{s}"


def convert(src: str) -> list[str]:
    out: list[str] = []
    last = ""
    for block in re.split(r"\n\s*\n", src.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        timing = next((l for l in lines if "-->" in l), None)
        if not timing:
            continue
        start = timing.split("-->")[0].strip()
        if start.count(":") == 1:      # "MM:SS.mmm" -> "00:MM:SS.mmm"
            start = "00:" + start
        for raw in lines[lines.index(timing) + 1:]:
            text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
            if not text or text == last:
                continue
            last = text
            out.append(f"{stamp(start)}  {text}")
    return out


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        return 64
    src = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    for line in convert(src):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
