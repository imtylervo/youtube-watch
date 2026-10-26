# Changelog

Versions follow [semver](https://semver.org): major = breaking CLI or output change, minor = new feature, patch = fix. The current version is in `VERSION`; each release has a git tag `vX.Y.Z`.

## 4.0.1 (2026-10-26)

- Cleanup before going public: removed links to a private repo, personal examples and notes, the comparison with the removed v1/v2 extractors and an unmeasured "~95% understanding" claim; proxy providers are examples, not recommendations; `transcript-quality.py` reasons are in English; README file layout and output list match the current scripts.

## 4.0.0 (2026-10-26)

- Removed the legacy extractors `extract.sh` (v1, scene changes only) and `extract-v2.sh` (fixed sampling + OCR on every frame). `extract-v3.sh` covers both: it adds a frame at every scene change, and `--ocr` reads on-screen text. Callers of `extract.sh` should call `extract-v3.sh` (same `transcript.txt` and `frames/` outputs; it has no `--scene`/`--range` options).

## 3.5.0 (2026-10-26)

- Removed the whisper.cpp tier (and its `~/.cache/whisper/ggml-*.bin` models). Tier C is now mlx-whisper on Apple Silicon, else faster-whisper. whisper.cpp scored 43.4% word error on the Vietnamese vlog test (mlx-whisper 13.3%, faster-whisper 13.9%) and invented lines over music. Without either Python package, Tier C is skipped with a message. The legacy `extract.sh` / `extract-v2.sh` are unchanged.

## 3.4.0 (2026-10-26)

- Tier C tries **mlx-whisper** first on Apple Silicon (`scripts/mlx-whisper-txt.py`), only when the model is already in the HuggingFace cache (exit 3 otherwise, then faster-whisper, then whisper.cpp). It reuses faster-whisper's Silero VAD and drops a segment that spans a whole ~30 s window with under 1 word/s (a stock line made up over music). On 5 min of a Vietnamese vlog against YouTube's captions: mlx-whisper large-v3-turbo 13.3% word error in 11 s, faster-whisper large-v3 13.9% in 274 s, whisper.cpp large-v3-turbo 43.4% in 13 s (it repeated "Hãy subscribe cho kênh ..." 8 times).
- When VAD finds no speech at all, the video is marked music/sound only (`transcript.whisper-rejected.txt`) instead of "no transcript".
- Sheet labels are drawn with Pillow when ffmpeg has no `drawtext` (Homebrew's ffmpeg), so every cell shows its frame number and time.
- Fix: with no known video language, Tier C crashed on macOS's bash 3.2 (`FW_LANG[@]: unbound variable`) and was skipped (since 3.2.0).
- `requirements.txt` lists the optional packages for the skill's `.venv` (Python 3.11).

## 3.3.1 (2026-10-26)

- Whisper output is checked like subtitles (`transcript-quality.py`). On a music-only video whisper.cpp wrote `*music*` tags and invented "We'll be right back"; that text is now rejected (kept as `transcript.whisper-rejected.txt`) and the video is planned as `no-speech`. `*music*` counts as a tag.
- Audio fallback: when every audio-only format 403s, the audio is taken from the 360p progressive stream (format 18), which still downloaded in that case.
- Warns when yt-dlp is more than 60 days old: an old yt-dlp was the cause of the 403s above (2026.03.17 failed, 2026.10.21 worked).
- `SKILL.md`: a "When something fails" section (update yt-dlp before trying a VPN; rerun the script instead of downloading by hand, and delete anything fetched by hand).

## 3.3.0 (2026-10-19)

- New `sheets/sheet_NN.jpg` (made by `scripts/make-sheets.py`): **every** kept frame, 16 per picture (4x4, 640x360 cells), each labelled with its frame number and time; `sheets/index.txt` lists the frames of each sheet. A 15-minute video fits in about 8 pictures.
- `SKILL.md` and `understanding.md` now say to open every sheet before watching or summarizing a video, and to report how many frames were looked at. Before, the skill only said to look at `overview.jpg` (~20 frames) and then "the frames you need", so a "watch this carefully" request could be answered from 3 pictures out of 131. Only a narrow question about one moment may skip the rest.
- If ffmpeg has no `drawtext` filter, the sheets are built without labels (the order is still in `index.txt`).

## 3.2.1 (2026-10-15)

- Videos with no speech (e.g. a screen recording with music only) no longer end up with 0 frames and a 0 s duration. The `(no transcript available)` placeholder is no longer read as speech, and the planner gets the video's real length from yt-dlp (`--duration`): with no transcript it samples a frame every 3 s over the whole video (`video_type: no-speech`); with a transcript that ends early it still covers the full length.

## 3.2.0 (2026-10-14)

- Audio fallback (Tier C) uses faster-whisper with Silero VAD when it is installed in the skill's `.venv`, and passes the video's language; whisper.cpp stays as the fallback. On a Vietnamese test clip, whisper.cpp running `large-v3-turbo` replaced real speech with an invented line; faster-whisper with the same model transcribed it correctly (4.7% off YouTube's captions on a 4.7-min vlog).
- yt-dlp gets `--js-runtimes node` when deno is missing (newer yt-dlp needs a JS runtime for YouTube; without it downloads 403).
- `transcript.source` can now be `faster-whisper-<model>`.

## 3.1.0 (2026-09-29)

- 720p frames by default, 403 retry with the embedded-player client before the 360p fallback.
- Scene-change frames, near-duplicate frames dropped, denser sampling when the picture keeps changing.
- Subtitles in the video's own language; unreliable subtitles fall back to Whisper (`large-v3-turbo` default).
- `understanding.md` with *About this video* and a frame-by-frame timeline; `sections/` for long videos; `overview.jpg`.
- Linux VPS support: portable Whisper lookup and on-demand proxy.

## 3.0.0 (2026-05-07)

- First release as its own repo: content-aware `extract-v3.sh`, 3-tier transcript (captions API, yt-dlp subtitles, whisper.cpp).
