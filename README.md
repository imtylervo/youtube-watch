# youtube-watch

A skill that lets Claude watch a video. Version in [`VERSION`](VERSION), changes in [CHANGELOG.md](CHANGELOG.md).

Watch any YouTube video the way a human would — see the frames, hear the audio, cross-reference what was shown with what was said.

https://github.com/user-attachments/assets/31727c53-8940-40c7-a324-eae3213855a1

A Claude Code (or any Anthropic-SDK / MCP-compatible) skill that:

1. Downloads the video and its transcript via `yt-dlp`.
2. Extracts frames with `ffmpeg`, **smart-sampled** based on what the speaker is actually referencing (zone-based extraction, not blind 1-frame-per-N-seconds).
3. Builds `understanding.md`: the author's title/description/chapters, then a timeline where each frame is followed by what was said until the next frame — so the AI never has to cross-reference by hand. Long videos are split into sections with a contents list, `overview.jpg` (one picture of ~20 frames) shows the whole video at a glance, and `sheets/` packs **every** frame, 16 per labelled picture, so the AI looks at all of them in a few reads.

## Why content-aware frames

Sampling blindly (one frame every N seconds) wastes most frames on a speaker's face, and sampling only at scene changes misses a static slide the speaker keeps pointing at. This skill reads the transcript first, classifies the video (tutorial-code / demo-ui / slide-presentation / livestream-chat / talking-head / vlog / mixed / no-speech) and samples **densely** (1 frame / 2-3 s) around the moments the speaker says "look at this", "click here", "next slide", "let me code", and **normally** (1 frame / 8-15 s) elsewhere, plus a frame at every scene change — hard cuts and gradual ones (a fade, a motion graphic building up) once the new picture holds, while a handheld or panning camera does not count.

## How it compares to claude-real-video

[claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video) (crv) does a similar job and is worth a look. The differences, going by its README on 2026-10-26:

- **Choosing frames:** crv keeps frames at scene changes plus a minimum rate. youtube-watch also reads the transcript first and samples densely where the speaker points at something ("look at this", "next slide", "let me code").
- **What Claude reads:** youtube-watch writes one `understanding.md` in which each frame sits next to what was said until the next frame. crv gives the frames, `transcript.txt` and a `MANIFEST.txt`.
- **Cost:** both are free and run locally; crv also offers a paid Pro version.

## Install

Runs on macOS and Linux. Windows (Git Bash) works as of 4.1.1 according to a contributor; the maintainer has not tested it.

### Claude Code plugin (one command)

```text
/plugin marketplace add imtylervo/youtube-watch
/plugin install youtube-watch@youtube-watch
```

For the optional Whisper tier, put the Python packages in `~/.local/share/youtube-watch/.venv` (see Dependencies); the plugin's own folder is replaced on every update.

### Claude Code (skill, git clone)

```bash
git clone https://github.com/imtylervo/youtube-watch.git ~/.claude/skills/youtube-watch
chmod +x ~/.claude/skills/youtube-watch/scripts/*.sh ~/.claude/skills/youtube-watch/scripts/*.py
```

The skill file at `~/.claude/skills/youtube-watch/SKILL.md` is auto-discovered by Claude Code.

### Dependencies

```bash
# Required (ffmpeg >= 5.1 recommended; older builds still work, overview.jpg uses a fallback flag)
brew install yt-dlp ffmpeg

# Optional — for faster transcripts on captioned videos (Tier A)
pip install --user youtube-transcript-api

# Optional — Whisper fallback for videos without (usable) captions (Tier C)
# Preferred: the skill's own venv (mlx-whisper on Apple Silicon, faster-whisper elsewhere)
uv venv --python 3.11 ~/.claude/skills/youtube-watch/.venv
uv pip install --python ~/.claude/skills/youtube-watch/.venv/bin/python -r requirements.txt
# Plugin install: same, in ~/.local/share/youtube-watch/.venv (found automatically)
# mlx-whisper runs only with a model already in ~/.cache/huggingface (it never downloads one);
# fetch it once with: hf download mlx-community/whisper-large-v3-turbo

# Optional — on-screen text with --ocr (English + Vietnamese)
brew install tesseract tesseract-lang

```

## Usage

### Default (v3, recommended)

```bash
~/.claude/skills/youtube-watch/scripts/extract-v3.sh \
    "https://youtu.be/XXXX"
```

A local file works too (the transcript then comes from Whisper on its audio):

```bash
~/.claude/skills/youtube-watch/scripts/extract-v3.sh ~/Movies/talk.mp4
```

Output in `~/.cache/yt-watch/<video-id>/`:
- `transcript.txt` — `MM:SS  text` timeline
- `transcript.source` — which tier won (`youtube-api` / `yt-dlp-vtt` / `mlx-whisper-<model>` / `faster-whisper-<model>` / `none`)
- `plan.json` — video classification + frame extraction zones
- `frames/frame_NNNN.jpg` — smart-sampled frames
- `frame_index.txt` — frame → timestamp + label (`normal` / `dense` / `scene`)
- `overview.jpg` (+ `overview.txt` with the times) — ~20 frames spread over the video in one picture
- `sheets/sheet_NN.jpg` (+ `sheets/index.txt`) — every frame, 16 per labelled picture
- `meta.json` — the author's title / description / chapters
- `understanding.md` — ★ start here: About + timeline (frame, then the speech around it); for long videos only the About + a contents list
- `sections/section_NN.md` — long videos: the timeline in pieces (author's chapters, else ~25 KB parts)
- `ocr.tsv` — on-screen text per frame (only with `--ocr`)

### Quality presets

```bash
extract-v3.sh URL --quality fast       # 360p, Whisper base
extract-v3.sh URL --quality balanced   # 480p
extract-v3.sh URL --quality high       # 720p  ← default
extract-v3.sh URL --quality max        # 1080p (code, dense slides)
```

Other flags: `--ocr` (on-screen text, needs tesseract), `--prefer-whisper` (skip subtitles, transcribe the audio), `--whisper-model NAME` (`large-v3-turbo` default; `large-v3`, `small`, `base`), `--no-whisper`, `--out DIR`, `--no-cleanup`.

### Override frame budget

```bash
extract-v3.sh URL --max-frames 500     # for longer / denser sampling
```

## How it works (v3, 5 stages)

```
Stage 1: yt-dlp — metadata (id, language, duration) + the author's title/description/chapters

Stage 2: 3-tier transcript fallback
  Tier A: youtube-transcript-api — instant when the video has captions
  Tier B: yt-dlp --write-auto-subs — 10-30s, covers most others (the video's own
          language, rolling captions de-duplicated)
  Tier C: local Whisper (mlx-whisper, else faster-whisper) — only when A+B fail OR the subtitles look unreliable
          (empty, mostly [Music], < 15 words/min); keeps the subtitles if Whisper
          also fails. Livestreams without captions, private videos, etc.

Stage 3: analyze-transcript.py
  — regex-detect speaker visual references:
       look-here     "look at this", "see here", "notice the"
       next-slide    "next slide", "moving on", "now let's"
       code-action   "let me write", "type this", "run this command"
       click-action  "click here", "press this", "select this"
       screen-share  "open VS Code", "switch to terminal", "share my screen"
       diagram       "this diagram", "the chart", "the architecture"
       demo          "let me show", "live demo", "here's how"
       (English and Vietnamese phrases)
  — classify video_type by which categories dominate (frequency-based for short videos)
  — emit JSON plan: zones (dense / normal / sparse) + frame budget

Stage 4: yt-dlp video download at chosen quality (default client → embedded-player
         client → Android 360p if YouTube 403s), then extract-frames-from-plan.py:
         planned timestamps + scene-change frames (hard cuts, and gradual
         changes once the new picture holds), denser when the picture keeps
         changing, near-identical frames dropped

Stage 5: make-overview.py → overview.jpg; optional ocr-frames.py;
         build-understanding.py → understanding.md (About + timeline; contents +
         sections/ for long videos). Cleanup heavy media (video.mp4, audio.*,
         whisper output) — keep just the digest-ready artifacts. Final workdir is
         ~5-30MB instead of 1-3GB.
```

## File layout

```
youtube-watch/
├── SKILL.md                              # the skill the AI reads
├── README.md, CHANGELOG.md, VERSION, LICENSE (MIT)
├── requirements.txt                      # optional Python packages for the skill's .venv
├── yt-watch.env.example                  # proxy template (copy to ~/.config/yt-watch.env)
├── references/vps-setup.md               # Linux / VPS setup and proxy
└── scripts/
    ├── extract-v3.sh                     # ★ entry point
    ├── get-transcript.py                 # youtube-transcript-api wrapper (Tier A)
    ├── pick-vtt.py                       # choose the subtitle track in the video's language
    ├── vtt-to-txt.py                     # WebVTT → "MM:SS  text", rolling captions de-duplicated
    ├── transcript-quality.py             # are the subtitles (or Whisper's text) real speech?
    ├── mlx-whisper-txt.py                # Tier C on Apple Silicon (GPU)
    ├── faster-whisper-txt.py             # Tier C on CPU (Linux / VPS)
    ├── analyze-transcript.py             # transcript → video classification + zone plan
    ├── extract-frames-from-plan.py       # plan + video → frames (scene changes, dedupe)
    ├── make-overview.py                  # overview.jpg: ~20 frames in one picture
    ├── make-sheets.py                    # sheets/: every frame, 16 per labelled picture
    ├── ocr-frames.py                     # optional on-screen text (tesseract)
    └── build-understanding.py            # understanding.md: About + timeline (+ sections/)
tests/                                    # python3 -m unittest discover tests
```

## Acknowledgements

- yt-dlp, ffmpeg, Tesseract, Pillow — the heavy lifters.
- mlx-whisper (Apple) and faster-whisper (SYSTRAN) — local STT fallback.
- youtube-transcript-api by jdepoix — Tier A speed wins.
- The 6 prior-art repos that informed v3's design: `bradautomates/claude-video`, `jordanrendric/claude-video-vision`, `0xchamin/mcptube`, `destinyfrancis/openclaw-knowledge-distiller`, `thoughtpunch/claudetube`, `michalparkola/tapestry-skills`.

## License

MIT. See `LICENSE`.
