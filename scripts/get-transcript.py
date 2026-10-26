#!/usr/bin/env python3
"""Fast YouTube transcript fetcher using youtube-transcript-api.

This bypasses yt-dlp's caption flow entirely — works on videos where
yt-dlp returns "no auto-captions" because youtube-transcript-api uses
the player_response timedtext endpoint directly.

Usage:
    get-transcript.py <video_id_or_url> --out path/to/transcript.txt

Output format (the `MM:SS  text` convention of every tier):
    0:05  All right, welcome. So today...
    0:08  ...the OpenClaw boot camp starts.

Returns exit code 0 on success, non-zero on failure (so shell scripts
can detect and fall through to the next tier).

Install:
    pip install youtube-transcript-api
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_video_id(url_or_id: str) -> str:
    if len(url_or_id) == 11 and not url_or_id.startswith("http"):
        return url_or_id
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([0-9A-Za-z_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    raise ValueError(f"Could not extract video id from: {url_or_id}")


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url_or_id")
    p.add_argument("--out", required=True, help="Output transcript.txt path")
    p.add_argument("--lang", default="en", help="Preferred language (comma-separated)")
    args = p.parse_args()

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        sys.stderr.write(
            "youtube-transcript-api not installed. Run:\n"
            "  pip install --user youtube-transcript-api\n"
        )
        return 2

    try:
        vid = extract_video_id(args.url_or_id)
    except ValueError as e:
        sys.stderr.write(f"{e}\n")
        return 3

    languages = [l.strip() for l in args.lang.split(",") if l.strip()] or ["en"]

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(vid, languages=languages)
    except Exception as e:
        sys.stderr.write(f"transcript fetch failed: {type(e).__name__}: {e}\n")
        return 4

    if not fetched or len(fetched) == 0:
        sys.stderr.write("transcript came back empty\n")
        return 5

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for snip in fetched:
        text = snip.text.strip().replace("\n", " ")
        if text:
            lines.append(f"{format_timestamp(snip.start)}  {text}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stderr.write(f"✓ wrote {len(lines)} transcript lines to {out_path}\n")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
