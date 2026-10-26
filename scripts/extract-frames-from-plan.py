#!/usr/bin/env python3
"""Extract frames from a video using a JSON plan from analyze-transcript.py.

The plan defines zones (start/end/every_sec). For each zone, this script
asks ffmpeg to seek to ts and grab a single frame. On top of the plan it also
  - adds a frame at every detected scene change (label "scene"), and
  - drops a frame that is (almost) pixel-identical to the last one kept, so a
    static slide yields one frame — while one new bullet or code line still
    counts as a change and is kept.
Kept frames are named frame_<NNNN>.jpg in chronological order, plus a companion
frame_index.txt (name, MM:SS, label) next to the frames directory.

Usage:
  extract-frames-from-plan.py <video.mp4> <plan.json> --out-dir <dir>
                              [--max-frames N] [--scene-threshold 0.3]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

VISUAL_SCENES_PER_MIN = 1.0   # at least this many picture changes a minute = visual-heavy video
VISUAL_EVERY_SEC = 10         # ...then sample the ordinary zones at least this often
SCENE_BURST_GAP = 3           # scene hits closer than this (s) are one change (camera flicker)
PRIORITY = {"scene": 0, "dense": 1}  # kept first when over the frame budget
FP_W, FP_H = 160, 90                 # fingerprint size: fine enough to see a text line
PIXEL_DELTA = 12                     # grey-level change that counts as "different"
DUP_RATIO = 0.001                    # <=0.1% (14 of 14400) pixels changed -> duplicate:
                                     # a mouse pointer, not a typed line


def fmt_ts(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def extract_frame(video: Path, ts_sec: int, out_path: Path) -> bool:
    """ffmpeg seek + single frame. Fast seek (-ss before -i) — accurate for 1-2s."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", fmt_ts(ts_sec),
        "-i", str(video),
        "-vframes", "1", "-q:v", "2",
        str(out_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0


def scene_timestamps(video: Path, threshold: float) -> list[int]:
    """Whole seconds at which the picture changes a lot (slide flip, app switch)."""
    cmd = [
        "ffmpeg", "-loglevel", "info", "-i", str(video), "-an",
        "-vf", f"fps=2,scale=320:-1,select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        sys.stderr.write("⚠ scene detection timed out — continuing without it\n")
        return []
    found = re.findall(r"pts_time:(\d+(?:\.\d+)?)", r.stderr)
    # ceil: pts_time is the first frame of the new scene; never land before the cut.
    return sorted({math.ceil(float(t)) for t in found})


def boost_for_visual(zones: list[dict], scenes: list[int], duration: int) -> list[dict]:
    """The transcript may give no visual cues (any language, any speaking style), but a
    picture that keeps changing is visual content. Then tighten the ordinary zones; the
    duplicate filter drops repeats. Dense zones and already-dense zones are left alone."""
    if duration <= 0:
        return zones
    changes, prev = 0, None
    for ts in sorted(scenes):
        if prev is None or ts - prev > SCENE_BURST_GAP:
            changes += 1
        prev = ts
    rate = changes / (duration / 60)
    if rate < VISUAL_SCENES_PER_MIN:
        return zones
    sys.stderr.write(f"→ visual-heavy video ({rate:.1f} scene changes/min): "
                     f"sampling ordinary zones at least every {VISUAL_EVERY_SEC}s\n")
    return [dict(z, every_sec=min(z["every_sec"], VISUAL_EVERY_SEC))
            if z.get("density", "normal") == "normal" else dict(z) for z in zones]


def fingerprint(image: Path) -> bytes | None:
    cmd = [
        "ffmpeg", "-loglevel", "error", "-i", str(image),
        "-vf", f"scale={FP_W}:{FP_H},format=gray",
        "-frames:v", "1", "-f", "rawvideo", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout if r.returncode == 0 and len(r.stdout) == FP_W * FP_H else None


def is_duplicate(a: bytes | None, b: bytes | None) -> bool:
    if a is None or b is None:
        return False
    changed = sum(1 for x, y in zip(a, b) if abs(x - y) > PIXEL_DELTA)
    return changed / len(a) <= DUP_RATIO


def cap_to_budget(cands: dict[int, str], budget: int) -> dict[int, str]:
    """Keep scene frames first, then dense, then the rest; thin the last group evenly."""
    if budget <= 0 or len(cands) <= budget:
        return cands
    kept: dict[int, str] = {}
    groups: dict[int, list[int]] = {}
    for ts, label in cands.items():
        groups.setdefault(PRIORITY.get(label, 2), []).append(ts)
    for prio in sorted(groups):
        members = sorted(groups[prio])
        room = budget - len(kept)
        if room <= 0:
            break
        if len(members) > room:
            step = len(members) / room
            members = [members[int(i * step)] for i in range(room)]
        kept.update({ts: cands[ts] for ts in members})
    return kept


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video", help="Path to video.mp4")
    p.add_argument("plan", help="Path to plan.json from analyze-transcript.py")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--max-frames", type=int, default=0, help="0 = no cap")
    p.add_argument("--scene-threshold", type=float, default=0.3)
    args = p.parse_args()

    video = Path(args.video)
    if not video.exists():
        sys.stderr.write(f"video not found: {video}\n")
        return 2
    plan = json.loads(Path(args.plan).read_text())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("frame_*.jpg"):  # numbering changes between runs
        stale.unlink()

    duration = plan.get("duration_sec", 0)
    zones = plan.get("zones", [])
    sys.stderr.write(f"→ video: {video.name}\n")
    sys.stderr.write(f"→ video_type: {plan.get('video_type')}\n")
    sys.stderr.write(f"→ duration: {fmt_ts(duration)}\n")
    sys.stderr.write(f"→ zones: {len(zones)}\n")
    sys.stderr.write(f"→ target frame budget: {plan.get('target_frame_count')}\n")

    # Candidate timestamps: plan zones, then scene changes (which win the label).
    scenes = scene_timestamps(video, args.scene_threshold)
    sys.stderr.write(f"→ scene changes detected: {len(scenes)}\n")
    zones = boost_for_visual(zones, scenes, duration)
    cands: dict[int, str] = {}
    for z in zones:
        every = max(1, z["every_sec"])
        ts = z["start_sec"]
        while ts < z["end_sec"]:
            cands[ts] = z.get("density", "normal")
            ts += every
    for ts in scenes:
        if duration and ts >= duration:
            continue
        cands[ts] = "scene"
    cands = cap_to_budget(cands, args.max_frames)
    timestamps = sorted(cands)
    sys.stderr.write(f"→ extracting {len(timestamps)} candidate frames…\n")

    index_lines = []
    failed = 0
    last_fp: bytes | None = None
    tmp_path = out_dir / "_candidate.jpg"
    for i, ts in enumerate(timestamps, 1):
        if not extract_frame(video, ts, tmp_path):
            failed += 1
        else:
            fp = fingerprint(tmp_path)
            if is_duplicate(last_fp, fp):
                tmp_path.unlink()
            else:
                name = f"frame_{len(index_lines) + 1:04d}.jpg"
                tmp_path.replace(out_dir / name)
                index_lines.append(f"{name}\t{ts // 60:02d}:{ts % 60:02d}\t{cands[ts]}")
                last_fp = fp
        if i % 50 == 0:
            sys.stderr.write(f"  {i}/{len(timestamps)} done\n")
    tmp_path.unlink(missing_ok=True)

    dropped = len(timestamps) - len(index_lines) - failed
    index_path = out_dir.parent / "frame_index.txt"
    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    sys.stderr.write(f"→ dropped {dropped} duplicate frames" + (f", {failed} could not be extracted" if failed else "") + "\n")
    sys.stderr.write(f"→ frame_index.txt: {len(index_lines)} entries → {index_path}\n")
    print(len(index_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
