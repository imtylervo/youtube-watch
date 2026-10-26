#!/usr/bin/env python3
"""Transcribe a 16 kHz mono WAV with mlx-whisper (Apple Silicon GPU) into transcript.txt lines.

  mlx-whisper-txt.py audio.wav --out transcript.txt [--model large-v3-turbo] [--lang vi]
  mlx-whisper-txt.py --check [--model large-v3-turbo]   # exit 0 if usable here, else 3

Output matches the other tiers: "MM:SS  text" (HH:MM:SS once the audio passes 1 h).
Same guards as faster-whisper-txt.py: Silero VAD (borrowed from faster-whisper) picks the
speech, and the previous text is not fed back in. When VAD finds no speech the output
file is left empty, so the caller can tell "music/sound only" from a failed run.
Exits 3 when the model is not already downloaded (no surprise multi-GB download).
"""
from __future__ import annotations

import argparse
import os
import sys

# mlx-community repo for each whisper model name the skill uses
REPOS = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
}


def stamp(seconds: float, long: bool) -> str:
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if long else f"{m:02d}:{s:02d}"


def cached(repo: str) -> bool:
    hub = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface")), "hub")
    return os.path.isdir(os.path.join(hub, "models--" + repo.replace("/", "--"), "snapshots"))


def invented(seg: dict, text: str) -> bool:
    """A segment spanning a whole ~30 s window with a few words is a stock line made up
    over music ("Hãy subscribe cho kênh ..."); real speech runs ~2-4 words per second."""
    span = seg["end"] - seg["start"]
    return span >= 20 and len(text.split()) / span < 1.0


def speech_clips(audio) -> list[float] | None:
    """[start, end, start, end, ...] in seconds, or None when VAD is unavailable."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return None
    clips: list[float] = []
    for seg in get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=1000, speech_pad_ms=400)):
        clips += [seg["start"] / 16000, seg["end"] / 16000]
    return clips


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true", help="only test that mlx-whisper and the model are here")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--lang", default=None, help="language code; omit to auto-detect")
    args = ap.parse_args()

    repo = REPOS.get(args.model, args.model)
    try:
        import mlx_whisper  # noqa: F401  (Apple Silicon only)
    except ImportError:
        sys.exit(3)
    if not cached(repo):
        print(f"mlx model not downloaded: {repo}", file=sys.stderr)
        sys.exit(3)
    if args.check:
        return
    if not args.audio or not args.out:
        ap.error("audio and --out are required")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from importlib import import_module
    read_wav = import_module("faster-whisper-txt").read_wav
    import mlx_whisper

    audio = read_wav(args.audio)
    clips = speech_clips(audio)
    long = len(audio) / 16000 >= 3600
    if clips == []:
        open(args.out, "w").close()
        print("no speech found by VAD", file=sys.stderr)
        return
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=repo, language=args.lang, condition_on_previous_text=False,
        clip_timestamps=clips if clips else "0")
    last = None
    with open(args.out, "w", encoding="utf-8") as f:
        for seg in result["segments"]:
            text = seg["text"].strip()
            if not text or text == last or invented(seg, text):
                continue
            f.write(f"{stamp(seg['start'], long)}  {text}\n")
            last = text
    print(f"language: {result.get('language')}", file=sys.stderr)


if __name__ == "__main__":
    main()
