---
name: youtube-watch
description: Make Claude actually watch a video. Downloads any YouTube/Vimeo/TikTok/X video or local `.mp4`/`.mov`, fetches a timestamped transcript (via captions API, yt-dlp auto-subs, or local Whisper fallback), and extracts smart-sampled frames so Claude can SEE the visuals AND READ the audio in one pass. Use this skill any time the user pastes a video link or path with a question — "summarize this", "tóm tắt video", "phân tích", "xem giúp em", "what's at the 30s mark", "explain this clip", "watch this", "analyze this footage", or even just a bare URL with no verb. Outputs `transcript.txt`, `frames/`, and a single combined `understanding.md` for Claude to read.
---

# youtube-watch

Default workflow — call `extract-v3.sh` and then read `understanding.md`. That's the whole skill in one sentence.

```bash
${CLAUDE_SKILL_DIR}/scripts/extract-v3.sh "<video-url-or-path>"
```

(Outside Claude Code, use the folder you cloned into, e.g. `~/.claude/skills/youtube-watch/scripts/extract-v3.sh`.)

**Look at every frame.** To watch, summarize or explain a video (including "xem", "tóm tắt", or a bare link), open **every** picture in `sheets/` (`sheet_01.jpg`, `sheet_02.jpg`, …) before answering. Each holds 16 frames, labelled with frame number and time, so a 15-min video is about 8 reads. Then open single frames from `frames/` to read small on-screen text (slides, tables, tweets, code). Do not answer from `overview.jpg` and a couple of frames: the picture often carries what the speaker never says (dashboards, numbers, quoted articles). In the answer, say how many frames you looked at (e.g. "looked at 131/131 frames"). Only for a narrow question about one moment ("what's at 2:30") may you open just that part. `overview.jpg` (~20 frames in one picture) is a first glance only.

After the script finishes, the workdir is `~/.cache/yt-watch/<video-id>/`. **Read `understanding.md` first.** It opens with *About this video* (the author's title, description and chapters — use them to correct names the automatic captions misspelled), then a timeline: each frame (with its timestamp and label) followed by what was said until the next frame, so you never have to cross-reference by hand. Then go through all of `sheets/` as above; for a focused question, prioritize the frames in that zone (and the `dense` frames the planner clustered around speaker visual references — see `frame_index.txt`).

## Output layout

```
~/.cache/yt-watch/<id>/
├── transcript.txt          MM:SS  text   (or HH:MM:SS for >1h)
├── transcript.source       which tier won: youtube-api | yt-dlp-vtt | mlx-whisper-<model> | faster-whisper-<model> | none
├── plan.json               video classification + extraction zones
├── frames/frame_NNNN.jpg   smart-sampled frames (near-identical ones dropped)
├── overview.jpg            ~20 frames spread over the video in ONE picture (times in overview.txt)
├── sheets/sheet_NN.jpg     ★ EVERY frame, 16 per picture, labelled "NNNN MM:SS" (list in sheets/index.txt)
├── transcript.whisper-rejected.txt  only when Whisper heard no speech (music/sound only)
├── frame_index.txt         frame_NNNN.jpg → MM:SS → label (normal | dense | scene)
├── ocr.tsv                 frame → on-screen text (only with --ocr)
├── meta.json               the author's title / description / chapters
├── understanding.md        ★ start here — about + timeline: frame, then the speech around it
└── sections/section_NN.md  long videos only: the timeline in pieces (see below)
```

`label` matters: `scene` frames are where the picture changed;  `dense` frames are clustered around timestamps where the speaker says "look at this" / "click here" / "next slide" / "let me code". When the user asks a focused question, prioritize the dense frames in that zone.

**Long videos:** when the timeline is over ~40 KB, `understanding.md` holds only the header, *About* and a *Contents* list (one line per section: time range, title, frame count, opening words). Read the contents, then open just the `sections/section_NN.md` you need instead of loading the whole video. Sections follow the author's chapters when there are any, otherwise ~25 KB parts.

## Quality presets

```bash
extract-v3.sh URL --quality fast       # 360p, whisper base
extract-v3.sh URL --quality balanced   # 480p
extract-v3.sh URL --quality high       # 720p  ← default (small on-screen text stays readable)
extract-v3.sh URL --quality max        # 1080p (code / dense slides)
extract-v3.sh URL --ocr                # also read on-screen text (needs: brew install tesseract tesseract-lang)
extract-v3.sh URL --prefer-whisper     # ignore YouTube captions, transcribe audio with Whisper
```

The log and `understanding.md` state the real resolution; if it is below what you asked for you get a warning (the source may not offer more, or the download fell back). If YouTube 403s the normal download, the script retries with the embedded-player client at the *same* height and only then falls back to Android's 360p stream.

Subtitles follow the video's own language (not the machine-translated English track). Whisper defaults to `large-v3-turbo` (multilingual) and gets the video's language. On Vietnamese, YouTube's own captions are still more accurate than Whisper, so use `--prefer-whisper` only when captions are missing or bad. mlx-whisper (Apple Silicon) never downloads a model: it runs only when the model is already in `~/.cache/huggingface`. faster-whisper (the VPS setup) downloads the model by name on first use.

Override frame budget directly with `--max-frames N` (e.g. `500` for 5h+ videos).

## How it works (5 stages, content-aware)

1. **yt-dlp metadata** + (cheap) audio download for fallback Whisper.
2. **3-tier transcript fallback:**
   - **A. youtube-transcript-api** — instant when the video has captions.
   - **B. yt-dlp `--write-auto-subs`** — fast (10-30s), covers most others.
   - **C. Local Whisper STT** — mlx-whisper on Apple Silicon when its model is already downloaded (GPU: ~11 s for 5 min of audio), else faster-whisper (CPU). Both use Silero VAD and are installed in the skill's `.venv` from `requirements.txt`. Slow (1-10 min), only when A+B fail (livestreams that haven't generated captions yet, private videos, audio-only sources).
   - **Unreliable subtitles count as a failure.** After A or B, `transcript-quality.py` checks them: no caption lines, more than half just `[Music]`-style tags, or under 15 spoken words/minute (videos ≥1 min). If so the script says why and tries Whisper on the audio; if Whisper yields nothing it keeps the subtitles (a copy is saved as `transcript.subs.txt`). Good subtitles are always used as-is — audio is never touched.
   - **Whisper output gets the same check.** On music-only audio Whisper writes `*music*` tags or invents a stock phrase ("We'll be right back"). If it fails, the video counts as having no speech (`no-speech` plan) and the rejected text is kept as `transcript.whisper-rejected.txt`. When that file exists, say the video has no voice-over (music/sound only), not that the transcript failed.
   - **Audio download fallback:** audio-only formats can all fail with HTTP 403 while the 360p stream that carries audio (format 18) still works; the script takes the audio from it.
3. **`analyze-transcript.py`** reads the transcript, regex-detects speaker visual references (`look-here` / `next-slide` / `code-action` / `click-action` / `screen-share` / `diagram` / `demo`), classifies the video as `tutorial-code` / `demo-ui` / `slide-presentation` / `livestream-chat` / `talking-head` / `vlog` / `mixed` (or `no-speech` when there is no transcript: then frames every 3 s over the video's real length), and emits a JSON plan with extraction zones.
4. **yt-dlp video DL** at the chosen resolution, then **`extract-frames-from-plan.py`** ffmpeg-seek-and-grabs one frame per planned timestamp.
   - Also adds a frame at every scene change (a hard cut, or a gradual one — a fade, a graphic building up — once the new picture holds; a moving camera does not count), drops near-identical frames, and — when the picture changes at least once a minute (independent of language or what the speaker says) — samples the ordinary zones at least every 10 s. This is a coarse signal: it also fires on edited talking-head videos (+~40% frames of a face), which is the accepted cost of not missing a static screen the speaker points at.
5. **Combined `understanding.md`** + cleanup (drops `video.mp4`, `audio.*`, raw whisper output — keeps the digest-ready files).

## Why content-aware (vs fixed sampling)

- **Fixed `1 frame / N seconds`:** a 2 h video gives 2000+ frames, mostly the same face, and fills the context with near-duplicates.
- **Scene changes only:** misses a long static slide the speaker keeps pointing at.
- **Content-aware (this skill):** reads the transcript first, then samples densely where the speaker says "look here" / "click this" / "let me code", sparsely elsewhere, plus every scene change. On a 2 h 18 min livestream that was 206 frames in about 2 minutes.

## When something fails

- **HTTP 403 on download:** the usual cause is an old yt-dlp (the script warns when it is over 60 days old). Update it first (`brew upgrade yt-dlp`, or `pip install -U yt-dlp` where it was installed with pip), then rerun the script. A VPN or proxy does not fix a 403; it only helps when YouTube asks to "confirm you're not a bot".
- **Rerun the script instead of downloading by hand.** If you still fetch something yourself (a higher resolution, an audio clip), put it in the session scratchpad and delete it in the same turn once you have looked at it. The script's cleanup only removes what the script downloaded.

## Reading frames after extraction

The AI is multimodal — open frame files directly with the `Read` tool to see colors, UI layout, person/object placement, expressions. Use `--ocr` only when you need to search or quote exact on-screen text (code, numbers, menu names) without opening every frame; for understanding the picture, just read the frames.

When you read a frame, mention its timestamp and label (normal|dense|scene) so the user can correlate with the spoken transcript. Cross-reference is the whole point — "at 35:42 the speaker says 'look at this' and frame_0055 shows the sales dashboard with the March column highlighted" is the kind of synthesis this skill enables.

## Running on a VPS / blocked IP (proxy)

YouTube bot-checks bare datacenter IPs ("Sign in to confirm you're not a bot"). The scripts handle this **on demand**: they try direct first, and only if the first request is blocked do they route the rest of that run through a proxy (`maybe_enable_proxy`). The proxy is scoped to the skill's process only — it is never a global/system proxy.

Set the proxy once in `~/.config/yt-watch.env` (chmod 600, auto-loaded). See [`references/vps-setup.md`](references/vps-setup.md) for the full Linux setup (deps + NordVPN HTTPS-proxy specifics) and copy `yt-watch.env.example` to get started. Key gotchas: install **yt-dlp via pip** (the standalone zipapp can't use an HTTPS proxy) with recent `requests`+`curl_cffi`, and address NordVPN servers as `<server>.proxy.nordvpn.com` so the TLS cert matches.
