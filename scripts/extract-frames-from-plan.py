#!/usr/bin/env python3
"""Extract frames from a video using a JSON plan from analyze-transcript.py.

The plan defines zones (start/end/every_sec). For each zone, this script
asks ffmpeg to seek to ts and grab a single frame. On top of the plan it also
  - adds a frame at every detected scene change (label "scene"): a hard cut, or a
    gradual one (a fade, a graphic that builds up) once the new picture holds, and
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
import tempfile
from pathlib import Path

VISUAL_SCENES_PER_MIN = 1.0   # at least this many picture changes a minute = visual-heavy video
VISUAL_EVERY_SEC = 10         # ...then sample the ordinary zones at least this often
SCENE_BURST_GAP = 3           # scene hits closer than this (s) are one change (camera flicker)
PRIORITY = {"scene": 0, "dense": 1, "gradual": 2}  # kept first when over the frame budget
# ("gradual" = a fade-type scene change: frequent in motion graphics, so it must not crowd
#  out the frames the transcript asked for; it is written to frame_index.txt as "scene")
FP_W, FP_H = 160, 90                 # fingerprint size: fine enough to see a text line
PIXEL_DELTA = 12                     # grey-level change that counts as "different"
DUP_RATIO = 0.001                    # <=0.1% (14 of 14400) pixels changed -> duplicate:
                                     # a mouse pointer, not a typed line
# Gradual changes: ffmpeg's scene score compares neighbouring frames, so a fade or a title
# that builds up over a second never scores high. A picture counts as changed when, at
# 2 fps, it differs from the one 1.5 s earlier (>= CHANGE_RATIO of pixels) far more than
# from the one 1 s later (CHANGE_HOLD times): it changed, then it holds. A moving camera
# changes about as much before as after, so handheld footage and slow pans do not count.
CHANGE_RATIO = 0.10
CHANGE_HOLD = 2.5
CHANGE_BACK, CHANGE_AHEAD = 3, 2     # samples at 2 fps: 1.5 s back, 1 s ahead


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


def changed_ratio(a: bytes, b: bytes) -> float:
    return sum(1 for x, y in zip(a, b) if abs(x - y) > PIXEL_DELTA) / len(a)


def gradual_changes(frames) -> list[int]:
    """Whole seconds at which a 2 fps stream of fingerprints changed and then held."""
    hits: list[int] = []
    window: list[bytes] = []
    last: bytes | None = None
    start = -10.0
    for i, fp in enumerate(frames):
        window.append(fp)
        if len(window) > CHANGE_BACK + CHANGE_AHEAD + 1:
            window.pop(0)
        if len(window) < CHANGE_BACK + CHANGE_AHEAD + 1:
            last = last or window[0]
            continue
        old, cur, new = window[0], window[CHANGE_BACK], window[-1]
        before = changed_ratio(old, cur)
        if before <= CHANGE_RATIO or changed_ratio(cur, last) <= CHANGE_RATIO:
            continue
        if before <= CHANGE_HOLD * changed_ratio(cur, new):
            continue
        t = math.ceil((i - CHANGE_AHEAD) / 2)
        if hits and t - start <= 1.5:
            hits[-1] = t          # the same fade, a moment later: keep where it settled
        else:
            hits.append(t)
            start = t
        last = cur
    return hits


def scene_timestamps(video: Path, threshold: float) -> tuple[list[int], list[int]]:
    """Whole seconds at which the picture changes: (hard cuts, gradual changes).
    One decode: ffmpeg logs the cuts on stderr and streams 2 fps fingerprints on stdout."""
    graph = (f"[0:v]fps=2,split=2[a][b];"
             f"[a]scale=320:-1,select='gt(scene,{threshold})',showinfo,nullsink;"
             f"[b]scale={FP_W}:{FP_H},format=gray[g]")
    cmd = ["ffmpeg", "-loglevel", "info", "-i", str(video), "-an",
           "-filter_complex", graph, "-map", "[g]", "-f", "rawvideo", "-"]
    size = FP_W * FP_H
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log)

        def stream():
            while True:
                fp = proc.stdout.read(size)
                if len(fp) < size:
                    return
                yield fp

        gradual = gradual_changes(stream())
        proc.wait()
        log.seek(0)
        found = re.findall(r"pts_time:(\d+(?:\.\d+)?)", log.read().decode("utf-8", "replace"))
    # ceil: pts_time is the first frame of the new scene; never land before the cut.
    return sorted({math.ceil(float(t)) for t in found}), gradual


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
    cuts, gradual = scene_timestamps(video, args.scene_threshold)
    # a picture settling just after a hard cut is that cut, already kept
    gradual = [t for t in gradual if all(abs(t - c) > SCENE_BURST_GAP - 1 for c in cuts)]
    scenes = sorted(set(cuts) | set(gradual))
    sys.stderr.write(f"→ scene changes detected: {len(scenes)} ({len(cuts)} cuts, {len(gradual)} gradual)\n")
    zones = boost_for_visual(zones, scenes, duration)
    cands: dict[int, str] = {}
    for z in zones:
        every = max(1, z["every_sec"])
        ts = z["start_sec"]
        while ts < z["end_sec"]:
            cands[ts] = z.get("density", "normal")
            ts += every
    for ts in gradual:
        if duration and ts >= duration:
            continue
        if cands.get(ts) != "dense":
            cands[ts] = "gradual"
    for ts in cuts:
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
                label = "scene" if cands[ts] == "gradual" else cands[ts]
                index_lines.append(f"{name}\t{ts // 60:02d}:{ts % 60:02d}\t{label}")
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
