#!/usr/bin/env python3
"""Build understanding.md as a timeline: every frame followed by what was said.

Reads <workdir>/frame_index.txt ("name\\tMM:SS\\tlabel"), <workdir>/transcript.txt
("MM:SS  text" or "HH:MM:SS  text") and, if present, <workdir>/ocr.tsv
("name\\ttext"). Each transcript line goes under the last frame at or before it;
lines before the first frame go under the first frame. Nothing is dropped.

--meta <meta.json> (yt-dlp's JSON) adds an "About this video" section: the author's
title, description and chapters, to check the spelling of names that automatic
captions get wrong.

A long timeline is split so it can be read piece by piece: understanding.md then holds
the header, the About section and a contents list, and the timeline itself is written
to <workdir>/sections/section_NN.md (the author's chapters if there are any, else parts
of a bounded size).

Usage: build-understanding.py <workdir> [--header header.md] [--meta meta.json]
       (markdown on stdout)
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import shutil
import sys
from pathlib import Path

DESCRIPTION_MAX = 1500   # chars of the author's description to show
SPLIT_CHARS = 40000      # timeline longer than this is split into sections
SECTION_MAX = 25000      # target size of one section file
CHAPTER_MAX = 38000      # an author's chapter is kept whole up to this size
OPENING_CHARS = 150      # how much of a section's first words the contents list quotes


def fmt(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def parse_transcript(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    last = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        m = re.match(r"^(?:(\d+):)?(\d+):(\d{2})\s+(.*)$", line)   # HH:MM:SS, MM:SS, or minutes >= 100
        if m:
            h = int(m.group(1) or 0)
            last = h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            out.append((last, m.group(4)))
        else:
            out.append((last, line.strip()))
    return out


def parse_index(text: str) -> list[tuple[str, int, str]]:
    frames = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        m = re.match(r"^(\d+):(\d{2})$", parts[1])
        if not m:
            continue
        label = parts[2] if len(parts) > 2 else ""
        frames.append((parts[0], int(m.group(1)) * 60 + int(m.group(2)), label))
    return sorted(frames, key=lambda f: f[1])


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def load_meta(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        meta = json.loads(read(Path(path)))
    except ValueError:
        return None
    return meta if isinstance(meta, dict) else None


def chapters_of(meta: dict | None) -> list[tuple[int, str]]:
    out = []
    for i, c in enumerate((meta or {}).get("chapters") or [], 1):
        try:
            out.append((int(float(c["start_time"])), str(c.get("title") or f"Chapter {i}")))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def render_about(meta: dict) -> list[str]:
    out = ["## About this video", ""]
    if meta.get("title"):
        out.append(f"**Title:** {meta['title']}")
    channel = meta.get("channel") or meta.get("uploader")
    if channel:
        out.append(f"**Channel:** {channel}")
    date = str(meta.get("upload_date") or "")
    if re.fullmatch(r"\d{8}", date):
        out.append(f"**Published:** {date[:4]}-{date[4:6]}-{date[6:]}")
    desc = (meta.get("description") or "").strip()
    if desc:
        if len(desc) > DESCRIPTION_MAX:
            desc = desc[:DESCRIPTION_MAX].rstrip() + "…"
        out += ["", "**Description (written by the author):**", "", desc]
    chapters = chapters_of(meta)
    if chapters:
        out += ["", "**Chapters (set by the author):**", ""]
        out += [f"- {fmt(start)} {title}" for start, title in chapters]
    out += ["", "_Automatic captions often misspell names and jargon: check spellings against "
                "the title and description above._", ""]
    return out


def render_overview(workdir: Path) -> list[str]:
    """Point at overview.jpg (made by make-overview.py) and say which time each cell is."""
    stamps = read(workdir / "overview.txt").split()
    if not stamps or not (workdir / "overview.jpg").exists():
        return []
    return ["## Overview picture", "",
            f"`overview.jpg` (same folder) shows {len(stamps)} frames spread evenly over the video, "
            "5 per row, ordered left to right, top to bottom. Their times: "
            + " ".join(stamps) + ".",
            "It is only a first glance: it does not replace looking at the frames.", ""]


def render_sheets(workdir: Path) -> list[str]:
    """List sheets/sheet_NN.jpg (made by make-sheets.py): every frame, 16 per picture."""
    rows = [l.split("\t") for l in read(workdir / "sheets" / "index.txt").splitlines()]
    rows = [r for r in rows if len(r) == 3 and (workdir / "sheets" / r[0]).exists()]
    if not rows:
        return []
    total = sum(len(r[2].split()) for r in rows)
    out = ["## Frame sheets (every frame)", "",
           f"`sheets/` holds all {total} frames in {len(rows)} pictures, 16 per picture (4 per row, "
           "left to right, top to bottom), each cell labelled with its frame number and time. "
           "To watch or summarize the video, open EVERY sheet below before answering; then open "
           "single frames from `frames/` to read small text. Say how many frames you looked at.", ""]
    out += [f"- `sheets/{name}`: frames {span}, {times.split()[0]}–{times.split()[-1]}"
            for name, span, times in rows]
    return out + [""]


class Block:
    """One frame and the speech from it until the next frame."""

    def __init__(self, name: str, ts: int, label: str, ocr: str, spoken: list[tuple[int, str]]):
        self.name, self.ts, self.label, self.ocr, self.spoken = name, ts, label, ocr, spoken
        tag = f" ({label})" if label else ""
        lines = [f"### [{fmt(ts)}] {name}{tag}"]
        if ocr:
            lines.append(f"> OCR: {ocr}")
        lines += [f"[{fmt(t)}] {s}" for t, s in spoken] or ["_(no speech)_"]
        lines.append("")
        self.text = "\n".join(lines)

    @property
    def end(self) -> int:
        return max([self.ts] + [t for t, _ in self.spoken])


def make_blocks(frames, lines, ocr) -> list[Block]:
    starts = [f[1] for f in frames]
    buckets: list[list[tuple[int, str]]] = [[] for _ in frames]
    for ts, text in lines:
        i = max(0, bisect.bisect_right(starts, ts) - 1)
        buckets[i].append((ts, text))
    return [Block(name, ts, label, ocr.get(name, ""), spoken)
            for (name, ts, label), spoken in zip(frames, buckets)]


def sectionize(blocks: list[Block], chapters: list[tuple[int, str]]) -> list[dict]:
    """Group blocks into sections: a new one at each author's chapter, or when the
    current one is full. Titles: the chapter (with part i/n if it had to be cut), else Part k."""
    starts = [c[0] for c in chapters]
    limit = CHAPTER_MAX if chapters else SECTION_MAX

    def chapter_of(ts: int) -> int:
        return bisect.bisect_right(starts, ts) - 1 if chapters else -2

    sections: list[dict] = []
    for b in blocks:
        ch = chapter_of(b.ts)
        cur = sections[-1] if sections else None
        if cur is None or cur["chapter"] != ch or cur["chars"] + len(b.text) > limit:
            cur = {"chapter": ch, "blocks": [], "chars": 0}
            sections.append(cur)
        cur["blocks"].append(b)
        cur["chars"] += len(b.text)

    per_chapter: dict[int, int] = {}
    for s in sections:
        per_chapter[s["chapter"]] = per_chapter.get(s["chapter"], 0) + 1
    seen: dict[int, int] = {}
    for k, s in enumerate(sections, 1):
        ch = s["chapter"]
        if ch == -2:
            s["title"] = f"Part {k}"
            continue
        base = chapters[ch][1] if ch >= 0 else "Start"
        seen[ch] = seen.get(ch, 0) + 1
        s["title"] = base if per_chapter[ch] == 1 else f"{base} (part {seen[ch]}/{per_chapter[ch]})"
    return sections


def opening_words(blocks: list[Block]) -> str:
    words = " ".join(text for b in blocks for _, text in b.spoken)
    return words if len(words) <= OPENING_CHARS else words[:OPENING_CHARS].rstrip() + "…"


def build(workdir: Path, header: str, meta: dict | None) -> tuple[str, dict[str, str]]:
    frames = parse_index(read(workdir / "frame_index.txt"))
    lines = parse_transcript(read(workdir / "transcript.txt"))
    ocr = {}
    for row in read(workdir / "ocr.tsv").splitlines():
        name, _, text = row.partition("\t")
        if text.strip():
            ocr[name] = text.strip()

    out = [header.rstrip(), ""]
    if meta:
        out += render_about(meta)
    out += render_overview(workdir)
    out += render_sheets(workdir)
    out += ["---", ""]
    if not frames:
        out += ["## Transcript", ""] + [f"[{fmt(t)}] {s}" for t, s in lines]
        return "\n".join(out) + "\n", {}

    blocks = make_blocks(frames, lines, ocr)
    sections: dict[str, str] = {}
    if sum(len(b.text) for b in blocks) <= SPLIT_CHARS:
        out += ["## Timeline (frame, then what was said until the next frame)", ""]
        out += [b.text for b in blocks]
        return "\n".join(out), sections

    out += ["## Contents", "",
            "The timeline is long, so it is split into sections. Read this list, then open only "
            "the section file(s) you need; each is a frame → speech timeline.", ""]
    for k, s in enumerate(sectionize(blocks, chapters_of(meta)), 1):
        name = f"section_{k:02d}.md"
        start, end = s["blocks"][0].ts, max(b.end for b in s["blocks"])
        sections[name] = (f"# {s['title']} [{fmt(start)}–{fmt(end)}]\n\n"
                          + "\n".join(b.text for b in s["blocks"]))
        out.append(f"- [{fmt(start)}–{fmt(end)}] **{s['title']}** → `sections/{name}` "
                   f"({len(s['blocks'])} frames) — opens: “{opening_words(s['blocks'])}”")
    out.append("")
    return "\n".join(out), sections


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("workdir")
    p.add_argument("--header", help="markdown file placed at the top")
    p.add_argument("--meta", help="yt-dlp JSON with the author's title, description, chapters")
    args = p.parse_args()
    work = Path(args.workdir)
    header = read(Path(args.header)) if args.header else ""
    main_md, sections = build(work, header, load_meta(args.meta))
    shutil.rmtree(work / "sections", ignore_errors=True)     # never leave a previous run's parts
    if sections:
        (work / "sections").mkdir()
        for name, text in sections.items():
            (work / "sections" / name).write_text(text, encoding="utf-8")
    sys.stdout.write(main_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
