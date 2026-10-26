#!/usr/bin/env python3
"""Make overview.jpg: one picture of up to 20 frames spread evenly over the video.

A long video has hundreds of frames; this one image shows what kind of video it is
(a face, code, slides, a UI) and where the interesting parts are, so individual frames
can then be opened on purpose. Frames are laid out left to right, top to bottom, five per
row; their times are written to overview.txt (space-separated, in the same order).
Skipped (no error) when there are fewer than two frames.

Usage: make-overview.py <workdir>     (reads frame_index.txt + frames/, writes overview.jpg/.txt)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

COLS, MAX_ROWS = 5, 4
CELL_W, CELL_H = 320, 180


def pick(rows: list[tuple[str, str]], k: int) -> list[tuple[str, str]]:
    """k entries evenly spread over rows, always including the first and the last."""
    if len(rows) <= k:
        return rows
    return [rows[round(i * (len(rows) - 1) / (k - 1))] for i in range(k)]


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        return 64
    work = Path(sys.argv[1])
    for stale in ("overview.jpg", "overview.txt"):       # never keep a previous run's picture
        (work / stale).unlink(missing_ok=True)
    index = work / "frame_index.txt"
    if not index.exists():
        return 0
    rows = []
    for line in index.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and (work / "frames" / parts[0]).exists():
            rows.append((parts[0], parts[1]))
    if len(rows) < 2:
        return 0

    chosen = pick(rows, COLS * MAX_ROWS)
    tile_rows = -(-len(chosen) // COLS)
    fit = (f"scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,"
           f"pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2:color=black,tile={COLS}x{tile_rows}")
    # concat resolves names relative to the list file, so it lives beside the frames.
    lst = work / "frames" / "_overview_list.txt"
    lst.write_text("".join(f"file '{name}'\nduration 1\n" for name, _ in chosen)
                   + f"file '{chosen[-1][0]}'\n",         # concat needs the last file repeated
                   encoding="utf-8")
    try:
        # "keep every input frame once": -fps_mode on ffmpeg >= 5.1, -vsync 0 on older ones
        for passthrough in (["-fps_mode", "passthrough"], ["-vsync", "0"]):
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-i", str(lst),
                 "-vf", fit, *passthrough, "-frames:v", "1", "-q:v", "3", str(work / "overview.jpg")],
                cwd=work / "frames", capture_output=True, text=True, timeout=120)
            if r.returncode == 0 or "Unrecognized option" not in r.stderr:
                break
    except subprocess.TimeoutExpired:
        sys.stderr.write("⚠ overview: ffmpeg timed out — skipping\n")
        return 0
    finally:
        lst.unlink(missing_ok=True)
    if r.returncode != 0 or not (work / "overview.jpg").exists():
        sys.stderr.write(f"⚠ overview: could not build ({r.stderr.strip()[:200]}) — skipping\n")
        (work / "overview.jpg").unlink(missing_ok=True)
        return 0
    (work / "overview.txt").write_text(" ".join(t for _, t in chosen), encoding="utf-8")
    sys.stderr.write(f"→ overview.jpg: {len(chosen)} frames, {COLS}x{tile_rows}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
