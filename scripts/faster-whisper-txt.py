#!/usr/bin/env python3
"""Transcribe a 16 kHz mono WAV with faster-whisper into transcript.txt lines.

  faster-whisper-txt.py audio.wav --out transcript.txt [--model large-v3-turbo] [--lang vi]

Output matches the other tiers: "MM:SS  text" (HH:MM:SS once the audio passes 1 h).
Uses Silero VAD and does not feed the previous text back in: on a Vietnamese test clip
whisper.cpp running the same turbo model replaced real speech with an invented
"subscribe to the channel" line, while this setup transcribed it correctly.
"""
from __future__ import annotations

import argparse
import os
import sys
import wave


def stamp(seconds: float, long: bool) -> str:
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if long else f"{m:02d}:{s:02d}"


def read_wav(path: str):
    import numpy as np
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
            sys.exit(f"expected 16 kHz mono 16-bit WAV: {path}")
        pcm = w.readframes(w.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--lang", default=None, help="language code; omit to auto-detect")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    audio = read_wav(args.audio)
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    segments, info = model.transcribe(audio, language=args.lang, beam_size=5, vad_filter=True,
                                      condition_on_previous_text=False)
    long = len(audio) / 16000 >= 3600
    last = None
    with open(args.out, "w", encoding="utf-8") as f:
        for seg in segments:
            text = seg.text.strip()
            if not text or text == last:
                continue
            f.write(f"{stamp(seg.start, long)}  {text}\n")
            last = text
    print(f"language: {info.language}", file=sys.stderr)


if __name__ == "__main__":
    main()
