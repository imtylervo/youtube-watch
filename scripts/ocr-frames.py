#!/usr/bin/env python3
"""Read on-screen text from the kept frames with tesseract (optional).

Reads <workdir>/frame_index.txt, OCRs <workdir>/frames/<name>, and writes
<workdir>/ocr.tsv ("name\\ttext", one line per frame). Frames whose text is
shorter than 20 characters are skipped (noise), text is cut at 300 characters, and text
identical to the previous frame's is skipped. Without tesseract this only
prints how to install it and exits 0, so --ocr never breaks a run.

Usage: ocr-frames.py <workdir>
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

MIN_CHARS = 20
MAX_CHARS = 300      # keep understanding.md readable: the gist of a slide, not a page
OCR_TIMEOUT = 60


def languages() -> str:
    r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    have = set(r.stdout.split())
    return "+".join(l for l in ("eng", "vie") if l in have) or "eng"


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        return 64
    work = Path(sys.argv[1])
    if not shutil.which("tesseract"):
        sys.stderr.write("⚠ --ocr: tesseract not found — skipping. "
                         "Install: brew install tesseract tesseract-lang\n")
        return 0
    lang = languages()
    index = work / "frame_index.txt"
    if not index.exists():
        sys.stderr.write("⚠ --ocr: no frame_index.txt (frame extraction failed?) — skipping\n")
        return 0
    names = [l.split("\t")[0] for l in index.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = []
    previous = ""
    for name in names:
        img = work / "frames" / name
        try:
            r = subprocess.run(["tesseract", str(img), "-", "-l", lang, "--psm", "6"],
                               capture_output=True, text=True, timeout=OCR_TIMEOUT)
        except subprocess.TimeoutExpired:
            continue
        text = " ".join(r.stdout.split())
        if len(text) >= MIN_CHARS and text != previous:   # same slide on the next frame: skip
            previous = text
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS].rstrip() + "…"
            rows.append(f"{name}\t{text}")
    if rows:
        (work / "ocr.tsv").write_text("\n".join(rows), encoding="utf-8")
    sys.stderr.write(f"→ ocr: text found on {len(rows)}/{len(names)} frames (lang {lang})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
