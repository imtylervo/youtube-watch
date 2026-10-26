#!/usr/bin/env python3
"""Pick the subtitle file in <dir> that matches the video's own language.

yt-dlp --write-auto-subs also downloads machine-translated tracks (e.g. an
English one for a Vietnamese video), and `ls | head -1` sorts them first. Prefer
the original-language track instead.

Usage: pick-vtt.py <dir> [lang]     (lang = "vi", "en", or "NA"/"" when unknown)
Prints the chosen path; exits 1 if the directory has no transcript.*.vtt.
"""
from __future__ import annotations

import sys
from pathlib import Path


def track(path: Path) -> str:
    # transcript.vi-orig.vtt -> "vi-orig"
    return path.name[len("transcript."):-len(".vtt")]


def pick(files: list[Path], lang: str) -> Path | None:
    if not files:
        return None
    tracks = {track(f): f for f in files}
    lang = lang.strip().lower()
    known = lang and lang not in ("na", "none", "unknown")
    if known:
        for want in (f"{lang}-orig", lang):
            if want in tracks:
                return tracks[want]
        for name, f in sorted(tracks.items()):
            if name.startswith(f"{lang}-"):
                return f
    else:
        for name, f in sorted(tracks.items()):
            if name.endswith("-orig"):
                return f
    for name, f in sorted(tracks.items()):
        if name == "en" or name.startswith("en-"):
            return f
    return sorted(files)[0]


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        return 64
    files = sorted(Path(sys.argv[1]).glob("transcript.*.vtt"))
    chosen = pick(files, sys.argv[2] if len(sys.argv) > 2 else "")
    if chosen is None:
        return 1
    print(chosen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
