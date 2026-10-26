#!/usr/bin/env python3
"""Make sheets/sheet_NN.jpg: EVERY kept frame, 16 per picture (4x4), each cell labelled.

overview.jpg shows only ~20 frames; reading a video properly means seeing all of them.
Opening 100+ frames one by one is slow, so this packs them into a few large pictures:
each cell is 640x360 with "NNNN MM:SS" (frame number, time) burnt into its top-left corner.
sheets/index.txt has one line per sheet: "sheet_NN.jpg<TAB>first-last frame<TAB>times".
If ffmpeg has no drawtext filter (no font support, e.g. Homebrew's ffmpeg), the labels are
drawn with Pillow instead; with neither, the sheets have no labels and index.txt still gives
the frames of each sheet in order (left to right, top to bottom).
Skipped (no error) when there are no frames.

Usage: make-sheets.py <workdir>     (reads frame_index.txt + frames/, writes sheets/)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

COLS, ROWS = 4, 4
PER_SHEET = COLS * ROWS
CELL_W, CELL_H = 640, 360


def chunks(rows: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    return [rows[i:i + PER_SHEET] for i in range(0, len(rows), PER_SHEET)]


def label(name: str, ts: str) -> str:
    """'frame_0012.jpg', '01:23' -> drawtext-escaped '0012  01\\:23'."""
    num = name.removeprefix("frame_").removesuffix(".jpg")
    return f"{num}  {ts}".replace(":", r"\:")


def stamp(out: Path, group: list[tuple[str, str]]) -> bool:
    """Draw the cell labels with Pillow (fallback when ffmpeg lacks drawtext)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    img = Image.open(out).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=26)
    for i, (name, ts) in enumerate(group):
        text = label(name, ts).replace("\\:", ":")
        x, y = (i % COLS) * CELL_W + 12, (i // COLS) * CELL_H + 12
        box = draw.textbbox((x, y), text, font=font)
        draw.rectangle((box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6), fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=(255, 255, 0))
    img.save(out, quality=88)
    return True


def build(group: list[tuple[str, str]], frames: Path, out: Path, labels: bool) -> subprocess.CompletedProcess:
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for name, _ in group:
        args += ["-i", str(frames / name)]
    chains = []
    for i, (name, ts) in enumerate(group):
        f = (f"[{i}:v]scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,"
             f"pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuvj420p")
        if labels:
            f += (f",drawtext=text='{label(name, ts)}':x=6:y=6:fontsize=26:fontcolor=yellow"
                  ":box=1:boxcolor=black@0.75:boxborderw=6")
        chains.append(f + f"[c{i}]")
    rows = -(-len(group) // COLS)
    cells = "".join(f"[c{i}]" for i in range(len(group)))
    graph = ";".join(chains) + f";{cells}concat=n={len(group)}:v=1:a=0,tile={COLS}x{rows}:color=white[out]"
    args += ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-q:v", "3", str(out)]
    return subprocess.run(args, capture_output=True, text=True, timeout=180)


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        return 64
    work = Path(sys.argv[1])
    sheets = work / "sheets"
    shutil.rmtree(sheets, ignore_errors=True)           # never keep a previous run's sheets
    index = work / "frame_index.txt"
    if not index.exists():
        return 0
    rows = []
    for line in index.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and (work / "frames" / parts[0]).exists():
            rows.append((parts[0], parts[1]))
    if not rows:
        return 0

    sheets.mkdir()
    labels, pillow, lines = True, False, []
    for n, group in enumerate(chunks(rows), 1):
        out = sheets / f"sheet_{n:02d}.jpg"
        try:
            r = build(group, work / "frames", out, labels)
            if r.returncode != 0 and labels and "drawtext" in r.stderr:
                labels = False                            # no font support: plain cells
                r = build(group, work / "frames", out, labels)
            if r.returncode == 0 and not labels and out.exists():
                pillow = stamp(out, group)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"⚠ sheets: ffmpeg timed out on {out.name} — skipping the rest\n")
            break
        if r.returncode != 0 or not out.exists():
            sys.stderr.write(f"⚠ sheets: could not build {out.name} ({r.stderr.strip()[:200]}) — skipping the rest\n")
            out.unlink(missing_ok=True)
            break
        first = group[0][0].removeprefix("frame_").removesuffix(".jpg")
        last = group[-1][0].removeprefix("frame_").removesuffix(".jpg")
        lines.append(f"{out.name}\t{first}-{last}\t{' '.join(t for _, t in group)}")
    if not lines:
        shutil.rmtree(sheets, ignore_errors=True)
        return 0
    (sheets / "index.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    covered = sum(len(l.split("\t")[2].split()) for l in lines)
    sys.stderr.write(f"→ sheets: {len(lines)} pictures, {covered}/{len(rows)} frames"
                     f"{'' if labels else ' (labels by Pillow: ffmpeg lacks drawtext)' if pillow else ' (no labels: ffmpeg lacks drawtext, Pillow missing)'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
