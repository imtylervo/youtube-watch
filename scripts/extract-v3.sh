#!/usr/bin/env bash
# youtube-watch v3 — content-aware extraction.
#
# Pipeline (5 stages):
#   Stage 1: yt-dlp metadata + audio download (cheap, fast)
#   Stage 2: Transcript via 3-tier fallback
#            Tier A: youtube-transcript-api (instant)
#            Tier B: yt-dlp --write-auto-subs (fast)
#            Tier C: local Whisper (mlx-whisper on Apple Silicon, else faster-whisper)
#   Stage 3: analyze-transcript.py reads transcript →
#            classifies video type + emits frame extraction plan JSON
#   Stage 4: yt-dlp pulls video at chosen res, then
#            extract-frames-from-plan.py samples per plan
#   Stage 5: understanding.md as a timeline: each frame, then what was said
#            until the next frame (plus on-screen text with --ocr)
#
# Usage:
#   extract-v3.sh <youtube-url> [opts]
#
# Options:
#   --quality fast|balanced|high|max  Video height 360|480|720|1080 (default: high)
#   --max-frames N                 Hard cap on frames (default: 300)
#   --no-whisper                   Skip Whisper Tier C (rely on YouTube subs only)
#   --prefer-whisper               Skip subtitles, transcribe the audio with Whisper
#   --whisper-model NAME           large-v3-turbo | large-v3 | small | base (default: large-v3-turbo)
#   --ocr                          Read on-screen text from frames (needs tesseract)
#   --out DIR                      Output directory (default $HOME/.cache/yt-watch/<id>)
#   --no-cleanup                   Keep video.mp4 + audio.* + raw frames
#
# Outputs in OUT_DIR (after cleanup):
#   transcript.txt          — MM:SS / HH:MM:SS  text
#   transcript.source       — youtube-api | yt-dlp-vtt | whisper-<model> | none
#   plan.json               — video classification + extraction zones
#   frames/frame_NNNN.jpg   — extracted frames per plan
#   overview.jpg            — ~20 frames spread over the video in one picture (+ overview.txt times)
#   sheets/sheet_NN.jpg     — EVERY frame, 16 per picture, labelled "NNNN MM:SS" (+ sheets/index.txt)
#   frame_index.txt         — frame → MM:SS + label (normal|dense|scene)
#   ocr.tsv                 — frame → on-screen text (only with --ocr)
#   meta.json               — the author's title / description / chapters (yt-dlp)
#   understanding.md        — start here: about + timeline (or contents, if long)
#   sections/section_NN.md  — the timeline, in pieces, for long videos

set -uo pipefail

# Optional outbound proxy for yt-dlp + youtube-transcript-api — bypasses
# datacenter-IP bot checks when running on a VPS. Set YT_PROXY to an
# HTTP or SOCKS5 URL (both yt-dlp and requests/httpx honour *_proxy env):
#   export YT_PROXY="http://user:pass@proxy.example.com:8080"
#   export YT_PROXY="socks5://user:pass@host:1080"
# Load a saved proxy but DON'T apply it yet — it's only switched on
# if a direct request gets blocked (YouTube bot-check). Keeps normal traffic
# direct; the proxy is used ONLY when actually needed.
[[ -z "${YT_PROXY:-}" && -f "$HOME/.config/yt-watch.env" ]] && source "$HOME/.config/yt-watch.env"
PROXY_ON=0
maybe_enable_proxy() {
  [[ "$PROXY_ON" == "1" || -z "${YT_PROXY:-}" ]] && return 0
  export HTTP_PROXY="$YT_PROXY" HTTPS_PROXY="$YT_PROXY" http_proxy="$YT_PROXY" https_proxy="$YT_PROXY"
  PROXY_ON=1
  echo "→ direct connection blocked — routing through proxy" >&2
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${YOUTUBE_WATCH_PYTHON:-python3}"
if [[ -x "$SCRIPT_DIR/../.venv/bin/python" ]]; then
  PYTHON="$SCRIPT_DIR/../.venv/bin/python"
elif [[ -z "${YOUTUBE_WATCH_PYTHON:-}" && -x "$HOME/.local/share/youtube-watch/.venv/bin/python" ]]; then
  # plugin installs: the plugin folder is replaced on update, so the venv lives outside it
  PYTHON="$HOME/.local/share/youtube-watch/.venv/bin/python"
fi

# YouTube changes often; a yt-dlp more than ~60 days old is the usual cause of HTTP 403.
YTDLP_VER=$(command yt-dlp --version 2>/dev/null | head -1)
YTDLP_AGE=$("$PYTHON" -c "import datetime,sys
try: print((datetime.date.today()-datetime.date(*map(int,sys.argv[1].split('.')[:3]))).days)
except Exception: print(0)" "$YTDLP_VER" 2>/dev/null || echo 0)
if [[ "$YTDLP_AGE" =~ ^[0-9]+$ ]] && (( YTDLP_AGE > 60 )); then
  echo "⚠ yt-dlp $YTDLP_VER is $YTDLP_AGE days old — if downloads fail with 403, update it first (brew upgrade yt-dlp, or pip install -U yt-dlp)" >&2
fi

# yt-dlp needs a JavaScript runtime for YouTube, else downloads 403 or formats go
# missing. It enables only deno by default; use node when that is what is installed.
if ! command -v deno >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
  yt-dlp() { command yt-dlp --js-runtimes node "$@"; }
fi

# YouTube's default client can return media URLs that reject yt-dlp's
# follow-up request with HTTP 403. Keep the normal client first so supported
# videos retain their best quality, then use the Android progressive stream.
YTDLP_YOUTUBE_CLIENT_ARGS=(--extractor-args "youtube:player_client=android")
# The embedded-player client still serves full DASH (720p/1080p) when the default
# client's media URLs 403, so try it before dropping to Android's 360p stream.
YTDLP_EMBEDDED_CLIENT_ARGS=(--extractor-args "youtube:player_client=web_embedded")

is_youtube_url() {
  case "$1" in
    http://youtube.com/*|https://youtube.com/*|http://www.youtube.com/*|https://www.youtube.com/*|http://m.youtube.com/*|https://m.youtube.com/*|http://youtu.be/*|https://youtu.be/*|http://youtube-nocookie.com/*|https://youtube-nocookie.com/*|http://www.youtube-nocookie.com/*|https://www.youtube-nocookie.com/*)
      return 0 ;;
    *)
      return 1 ;;
  esac
}

URL=""
QUALITY="high"
MAX_FRAMES=300
WANT_WHISPER=1
WHISPER_MODEL="large-v3-turbo"   # multilingual; ~7s for 4 min of audio on Apple Silicon
WHISPER_MODEL_SET=0
PREFER_WHISPER=0
WANT_OCR=0
OUT=""
KEEP_HEAVY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quality)        QUALITY="$2";       shift 2 ;;
    --max-frames)     MAX_FRAMES="$2";    shift 2 ;;
    --no-whisper)     WANT_WHISPER=0;     shift ;;
    --whisper-model)  WHISPER_MODEL="$2"; WHISPER_MODEL_SET=1; shift 2 ;;
    --prefer-whisper) PREFER_WHISPER=1;   shift ;;
    --ocr)            WANT_OCR=1;         shift ;;
    --out)            OUT="$2";           shift 2 ;;
    --no-cleanup)     KEEP_HEAVY=1;       shift ;;
    -h|--help)        sed -n '2,41p' "$0"; exit 0 ;;
    *) [[ -z "$URL" ]] && URL="$1" && shift && continue;
       echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$URL" ]] && { echo "usage: extract-v3.sh <youtube-url> [opts]" >&2; exit 1; }

case "$QUALITY" in
  fast)      MAX_HEIGHT=360; [[ "$WHISPER_MODEL_SET" == "0" ]] && WHISPER_MODEL="base" ;;
  balanced)  MAX_HEIGHT=480 ;;
  high)      MAX_HEIGHT=720 ;;
  max)       MAX_HEIGHT=1080 ;;
  *) echo "unknown --quality: $QUALITY" >&2; exit 1 ;;
esac

# A local video file (.mp4, .mov, ...): no captions to fetch and nothing to download;
# the transcript comes from Whisper on its audio and the frames from the file itself.
LOCAL_FILE=""
if [[ -f "$URL" ]]; then LOCAL_FILE="$(cd "$(dirname "$URL")" && pwd)/$(basename "$URL")"; fi

# id + the video's own language (decides the real subtitle track; "NA" = unknown)
video_meta() { yt-dlp --print "%(id)s|%(language)s|%(duration)s" --no-warnings "$URL" 2>/dev/null | head -1; }
if [[ -n "$LOCAL_FILE" ]]; then
  LOCAL_ID=$(printf '%s' "$(basename "${LOCAL_FILE%.*}")" | tr -c 'A-Za-z0-9_-' '_')
  LOCAL_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$LOCAL_FILE" 2>/dev/null | cut -d. -f1)
  META="${LOCAL_ID}|NA|${LOCAL_DURATION:-NA}"
else
  META=$(video_meta)
  # Direct request blocked (YouTube bot-check)? Switch to the proxy and retry once.
  if [[ "$META" != *"|"*"|"* ]]; then maybe_enable_proxy; META=$(video_meta); fi
fi
if [[ "$META" == *"|"*"|"* ]]; then
  VID_ID="${META%%|*}"; META_REST="${META#*|}"
  VIDEO_LANG="${META_REST%%|*}"; VIDEO_LANG="${VIDEO_LANG%%-*}"
  META_DURATION="${META_REST#*|}"
else
  VID_ID="video"; VIDEO_LANG="NA"; META_DURATION=""
fi
[[ "$META_DURATION" =~ ^[0-9]+(\.[0-9]+)?$ ]] || META_DURATION=0   # NA for live streams
[[ -z "$VID_ID" ]] && VID_ID="video"
[[ -z "$VIDEO_LANG" || "$VIDEO_LANG" == "None" ]] && VIDEO_LANG="NA"
[[ -z "$OUT" ]] && OUT="$HOME/.cache/yt-watch/${VID_ID}"
mkdir -p "$OUT/frames"

# The author's own title, description and chapters (best effort): names that automatic
# captions get wrong are usually spelled right here.
if [[ -n "$LOCAL_FILE" ]]; then
  "$PYTHON" -c "import json,sys; json.dump({'title': sys.argv[1]}, open(sys.argv[2], 'w'))" \
      "$(basename "$LOCAL_FILE")" "$OUT/meta.json"
elif ! yt-dlp --dump-single-json --skip-download --no-playlist --no-warnings "$URL" > "$OUT/meta.json" 2>/dev/null; then
  rm -f "$OUT/meta.json"
fi

echo "→ video id:        $VID_ID"
echo "→ output:          $OUT"
echo "→ quality:         $QUALITY (max ${MAX_HEIGHT}p)"
echo "→ whisper model:   $WHISPER_MODEL"
echo "→ frame budget:    $MAX_FRAMES"
echo

START_TIME=$(date +%s)

# ─── Stage 1+2: Audio + Transcript ─────────────────────────────────────────
TRANSCRIPT_TXT="$OUT/transcript.txt"
TRANSCRIPT_TIER=""
rm -f "$OUT/transcript.whisper-rejected.txt"   # never keep a verdict from an earlier run

if [[ "$PREFER_WHISPER" == "1" && "$WANT_WHISPER" == "0" ]]; then
  echo "⚠ --prefer-whisper ignored because --no-whisper is set" >&2
  PREFER_WHISPER=0
fi

# YouTube also offers machine-translated subtitle tracks; prefer the video's own language.
echo "→ video language:  $VIDEO_LANG"
if [[ "$VIDEO_LANG" == "NA" ]]; then
  TRANSCRIPT_LANGS="en,vi"
  SUB_LANGS=".*-orig,en.*"
else
  TRANSCRIPT_LANGS="${VIDEO_LANG},en,vi"
  SUB_LANGS="${VIDEO_LANG}.*,${VIDEO_LANG}-orig,en.*"
fi

# Tier A: youtube-transcript-api
GET_TRANSCRIPT="$SCRIPT_DIR/get-transcript.py"
if [[ -z "$LOCAL_FILE" && "$PREFER_WHISPER" == "0" ]] && [[ -x "$GET_TRANSCRIPT" ]] && "$PYTHON" -c "import youtube_transcript_api" 2>/dev/null; then
  echo "→ Tier A: youtube-transcript-api…"
  if "$PYTHON" "$GET_TRANSCRIPT" "$URL" --out "$TRANSCRIPT_TXT" --lang "$TRANSCRIPT_LANGS" 2>&1 | tail -1 >&2; then
    LINES=$(wc -l < "$TRANSCRIPT_TXT" 2>/dev/null | tr -d ' ' || echo 0)
    if [[ "$LINES" -gt 5 ]]; then
      echo "→ transcript:      $TRANSCRIPT_TXT ($LINES lines via youtube-api)"
      TRANSCRIPT_TIER="youtube-api"
    fi
  fi
fi

# Tier B: yt-dlp --write-auto-subs
if [[ -z "$LOCAL_FILE" && -z "$TRANSCRIPT_TIER" && "$PREFER_WHISPER" == "0" ]]; then
  echo "→ Tier B: yt-dlp auto-subs…"
  yt-dlp --skip-download --write-subs --write-auto-subs \
         --sub-langs "$SUB_LANGS" --sub-format "vtt/best" \
         --convert-subs vtt \
         -o "$OUT/transcript.%(ext)s" --no-warnings "$URL" >&2 || true
  TRANSCRIPT_VTT=$("$PYTHON" "$SCRIPT_DIR/pick-vtt.py" "$OUT" "$VIDEO_LANG" 2>/dev/null || true)
  if [[ -n "$TRANSCRIPT_VTT" ]]; then
    "$PYTHON" "$SCRIPT_DIR/vtt-to-txt.py" "$TRANSCRIPT_VTT" > "$TRANSCRIPT_TXT"
    LINES=$(wc -l < "$TRANSCRIPT_TXT" 2>/dev/null | tr -d ' ' || echo 0)
    if [[ "$LINES" -gt 5 ]]; then
      echo "→ transcript:      $TRANSCRIPT_TXT ($LINES lines via yt-dlp vtt)"
      TRANSCRIPT_TIER="yt-dlp-vtt"
    fi
  fi
fi

# Subtitles exist but look unreliable (nearly empty, or just [Music] tags)? Try the
# audio instead, and keep the subtitles if that fails too. Good subtitles are used as-is.
SUBS_TIER=""
if [[ -n "$TRANSCRIPT_TIER" && "$WANT_WHISPER" == "1" && "$PREFER_WHISPER" == "0" ]]; then
  if ! QUALITY_WHY=$("$PYTHON" "$SCRIPT_DIR/transcript-quality.py" "$TRANSCRIPT_TXT" --duration "$META_DURATION"); then
    echo "⚠ subtitles look unreliable ($QUALITY_WHY) — trying Whisper on the audio"
    SUBS_TIER="$TRANSCRIPT_TIER"
    cp "$TRANSCRIPT_TXT" "$OUT/transcript.subs.txt"
    TRANSCRIPT_TIER=""
  fi
fi

# Tier C: local Whisper STT (download audio first). mlx-whisper on Apple Silicon when the
# model is already downloaded (GPU, ~25x faster than faster-whisper on CPU, same accuracy
# on a Vietnamese vlog), else faster-whisper (CPU; the VPS setup). Both use Silero VAD.
# whisper.cpp was dropped in 3.5.0: 43% word error on that vlog, invented lines over music.
if [[ -z "$TRANSCRIPT_TIER" ]] && [[ "$WANT_WHISPER" == "1" ]]; then
  USE_MLX=0; USE_FW=0
  "$PYTHON" "$SCRIPT_DIR/mlx-whisper-txt.py" --check --model "$WHISPER_MODEL" 2>/dev/null && USE_MLX=1
  "$PYTHON" -c "import faster_whisper" 2>/dev/null && USE_FW=1
  if [[ "$USE_MLX" == "0" && "$USE_FW" == "0" ]]; then
    echo "⚠ no local Whisper — skipping Tier C (install requirements.txt into the skill's .venv)"
  else
    if [[ "$USE_MLX" == "1" ]]; then
      echo "→ Tier C: mlx-whisper ($WHISPER_MODEL)…"
    else
      echo "→ Tier C: faster-whisper ($WHISPER_MODEL)…"
    fi
    AUDIO_M4A="$OUT/audio.m4a"
    [[ -n "$LOCAL_FILE" ]] && AUDIO_M4A="$LOCAL_FILE"   # ffmpeg reads the audio straight from it
    AUDIO_WAV="$OUT/audio.wav"
    AUDIO_FORMAT="139/140/bestaudio[ext=m4a]/bestaudio"
    if [[ ! -s "$AUDIO_M4A" ]]; then
      yt-dlp -f "$AUDIO_FORMAT" -o "$AUDIO_M4A" --no-warnings "$URL" >&2 || true
    fi
    # Same 403 as the video download: retry with the embedded-player client.
    if [[ ! -s "$AUDIO_M4A" ]] && is_youtube_url "$URL"; then
      echo "⚠ audio download failed; retrying with the embedded-player client…" >&2
      rm -f "$AUDIO_M4A" "$AUDIO_M4A".part 2>/dev/null
      yt-dlp "${YTDLP_EMBEDDED_CLIENT_ARGS[@]}" -f "$AUDIO_FORMAT" \
             -o "$AUDIO_M4A" --no-warnings "$URL" >&2 || true
    fi
    # Audio-only formats can all 403 (SABR) while the progressive 360p mp4 (format 18,
    # video + audio in one file) still downloads: take its audio track.
    if [[ ! -s "$AUDIO_M4A" ]] && is_youtube_url "$URL"; then
      echo "⚠ audio-only download failed; trying the 360p stream that carries audio…" >&2
      rm -f "$AUDIO_M4A" "$AUDIO_M4A".part 2>/dev/null
      yt-dlp "${YTDLP_YOUTUBE_CLIENT_ARGS[@]}" -f "18" \
             -o "$AUDIO_M4A" --no-warnings "$URL" >&2 || true
    fi
    if [[ ! -s "$AUDIO_M4A" ]]; then
      echo "⚠ could not download the audio — skipping Tier C" >&2
    else
      if [[ ! -s "$AUDIO_WAV" ]]; then
        ffmpeg -y -i "$AUDIO_M4A" -ar 16000 -ac 1 -c:a pcm_s16le "$AUDIO_WAV" 2>>"$OUT/ffmpeg.log"
      fi
      FW_LANG=(); [[ "$VIDEO_LANG" != "NA" ]] && FW_LANG=(--lang "$VIDEO_LANG")
      if [[ "$USE_MLX" == "1" ]]; then
        "$PYTHON" "$SCRIPT_DIR/mlx-whisper-txt.py" "$AUDIO_WAV" --model "$WHISPER_MODEL" \
            ${FW_LANG[@]+"${FW_LANG[@]}"} --out "$OUT/whisper-out.fw.txt" 2>&1 | grep -v "Fetching" | tail -3 >&2
      else
        "$PYTHON" "$SCRIPT_DIR/faster-whisper-txt.py" "$AUDIO_WAV" --model "$WHISPER_MODEL" \
            ${FW_LANG[@]+"${FW_LANG[@]}"} --out "$OUT/whisper-out.fw.txt" 2>&1 | tail -3 >&2
      fi
    fi
    FW_NAME="faster-whisper"; [[ "$USE_MLX" == "1" ]] && FW_NAME="mlx-whisper"
    if [[ -f "$OUT/whisper-out.fw.txt" && ! -s "$OUT/whisper-out.fw.txt" ]]; then
      # Ran fine but VAD found no speech at all: music/sound only.
      echo "⚠ $FW_NAME found no speech — treating the video as music/sound only"
      echo "(VAD found no speech)" > "$OUT/transcript.whisper-rejected.txt"
    elif [[ -s "$OUT/whisper-out.fw.txt" ]]; then
      cp "$OUT/whisper-out.fw.txt" "$TRANSCRIPT_TXT"
      LINES=$(wc -l < "$TRANSCRIPT_TXT" 2>/dev/null | tr -d ' ' || echo 0)
      echo "→ transcript:      $TRANSCRIPT_TXT ($LINES lines via $FW_NAME $WHISPER_MODEL)"
      TRANSCRIPT_TIER="$FW_NAME-$WHISPER_MODEL"
    fi
    # On music-only audio Whisper writes *music* tags or invents a stock phrase
    # ("We'll be right back"). The same check as for subtitles catches both.
    if [[ "$TRANSCRIPT_TIER" == *whisper-* ]] && \
       ! WHY=$("$PYTHON" "$SCRIPT_DIR/transcript-quality.py" "$TRANSCRIPT_TXT" --duration "$META_DURATION"); then
      echo "⚠ Whisper heard no real speech ($WHY) — treating the video as music/sound only"
      mv "$TRANSCRIPT_TXT" "$OUT/transcript.whisper-rejected.txt"
      TRANSCRIPT_TIER=""
    fi
  fi
fi

if [[ -z "$TRANSCRIPT_TIER" && -n "$SUBS_TIER" ]]; then
  echo "→ Whisper produced nothing — keeping the (unreliable) subtitles"
  cp "$OUT/transcript.subs.txt" "$TRANSCRIPT_TXT"
  TRANSCRIPT_TIER="$SUBS_TIER"
fi

if [[ -z "$TRANSCRIPT_TIER" ]]; then
  echo "→ no transcript (all 3 tiers failed)"
  [[ "$PREFER_WHISPER" == "1" ]] && echo "  (--prefer-whisper skipped the subtitle tiers — rerun without it to use YouTube captions)"
  echo "(no transcript available)" > "$TRANSCRIPT_TXT"
  TRANSCRIPT_TIER="none"
fi
echo "$TRANSCRIPT_TIER" > "$OUT/transcript.source"

T_TRANSCRIPT_DONE=$(date +%s)
echo "→ stage 1+2 complete: $((T_TRANSCRIPT_DONE - START_TIME))s"
echo

# ─── Stage 3: Analyze transcript → frame plan ──────────────────────────────
echo "→ Stage 3: analyzing transcript → frame plan…"
PLAN_JSON="$OUT/plan.json"
ANALYZER="$SCRIPT_DIR/analyze-transcript.py"
"$PYTHON" "$ANALYZER" "$TRANSCRIPT_TXT" --out "$PLAN_JSON" --max-frames "$MAX_FRAMES" --duration "$META_DURATION"
VIDEO_TYPE=$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['video_type'])" "$PLAN_JSON" 2>/dev/null || echo "?")
TARGET_FRAMES=$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['target_frame_count'])" "$PLAN_JSON" 2>/dev/null || echo "?")
KEY_MOMENTS=$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['key_moments_count'])" "$PLAN_JSON" 2>/dev/null || echo "?")
DURATION=$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['duration_sec'])" "$PLAN_JSON" 2>/dev/null || echo "?")
echo "→ video_type:      $VIDEO_TYPE"
echo "→ duration:        ${DURATION}s"
echo "→ key_moments:     $KEY_MOMENTS"
echo "→ target_frames:   $TARGET_FRAMES"
echo

# ─── Stage 4: Download video + extract frames per plan ─────────────────────
echo "→ Stage 4: downloading video at ${MAX_HEIGHT}p + extracting frames per plan…"
VIDEO_FILE="$OUT/video.mp4"
# Local file: link it in (cleanup removes only the link, never the user's file).
[[ -n "${LOCAL_FILE:-}" ]] && ln -sf "$LOCAL_FILE" "$VIDEO_FILE"
if [[ ! -f "$VIDEO_FILE" ]]; then
  DOWNLOAD_STATUS=0
  DASH_FORMAT="bestvideo[height<=${MAX_HEIGHT}][ext=mp4]+bestaudio[ext=m4a]/best[height<=${MAX_HEIGHT}]/best"
  yt-dlp -f "$DASH_FORMAT" \
         --merge-output-format mp4 -o "$OUT/video.%(ext)s" --no-warnings "$URL" >&2 || DOWNLOAD_STATUS=$?

  # A failed DASH download can leave a video.f*.mp4 fragment that looks valid
  # to a broad glob. Remove those fragments before each retry/check.
  if [[ ! -s "$VIDEO_FILE" ]] && is_youtube_url "$URL"; then
    echo "⚠ YouTube media download failed; retrying with the embedded-player client (up to ${MAX_HEIGHT}p)…" >&2
    rm -f "$OUT"/video.f*.mp4 "$OUT"/video*.part "$OUT"/video*.ytdl 2>/dev/null
    if yt-dlp "${YTDLP_EMBEDDED_CLIENT_ARGS[@]}" -f "$DASH_FORMAT" \
             --merge-output-format mp4 -o "$OUT/video.%(ext)s" --no-warnings "$URL" >&2; then
      DOWNLOAD_STATUS=0
    else
      DOWNLOAD_STATUS=$?
    fi
  fi
  if [[ ! -s "$VIDEO_FILE" ]] && is_youtube_url "$URL"; then
    echo "⚠ still failing; last resort: Android progressive stream (usually only 360p)…" >&2
    rm -f "$OUT"/video.f*.mp4 "$OUT"/video*.part "$OUT"/video*.ytdl 2>/dev/null
    if yt-dlp "${YTDLP_YOUTUBE_CLIENT_ARGS[@]}" -f "best[height<=${MAX_HEIGHT}][ext=mp4]/best[height<=${MAX_HEIGHT}]/18" \
             --merge-output-format mp4 -o "$OUT/video.%(ext)s" --no-warnings "$URL" >&2; then
      DOWNLOAD_STATUS=0
    else
      DOWNLOAD_STATUS=$?
    fi
  fi

  if [[ "$DOWNLOAD_STATUS" -ne 0 || ! -s "$VIDEO_FILE" ]]; then
    echo "video file not found in $OUT" >&2
    exit 1
  fi
fi
echo "→ video saved:     $VIDEO_FILE"

EXTRACTOR="$SCRIPT_DIR/extract-frames-from-plan.py"
RESOLUTION=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$VIDEO_FILE" 2>/dev/null | head -1)
[[ -z "$RESOLUTION" ]] && RESOLUTION="unknown"
echo "→ resolution:      $RESOLUTION (asked for up to ${MAX_HEIGHT}p)"
VIDEO_HEIGHT="${RESOLUTION##*x}"
if [[ "$VIDEO_HEIGHT" =~ ^[0-9]+$ ]] && (( VIDEO_HEIGHT * 10 < MAX_HEIGHT * 9 )); then
  echo "⚠ got ${VIDEO_HEIGHT}p, below the ${MAX_HEIGHT}p requested — the source may not offer more, or the download fell back; small text may be hard to read" >&2
fi
ACTUAL_FRAMES=$("$PYTHON" "$EXTRACTOR" "$VIDEO_FILE" "$PLAN_JSON" --out-dir "$OUT/frames" --max-frames "$MAX_FRAMES")
echo "→ frames extracted: $ACTUAL_FRAMES → $OUT/frames"

T_FRAMES_DONE=$(date +%s)
echo "→ stage 3+4 complete: $((T_FRAMES_DONE - T_TRANSCRIPT_DONE))s"
echo

# ─── Stage 5: understanding.md (timeline: frame → what was said) ───────────
rm -f "$OUT/ocr.tsv"   # never mix in text from an earlier run's frames
if [[ "$WANT_OCR" == "1" ]]; then
  echo "→ OCR: reading on-screen text from frames…"
  "$PYTHON" "$SCRIPT_DIR/ocr-frames.py" "$OUT" >&2
fi

UNDERSTAND="$OUT/understanding.md"
HEADER_MD="$OUT/header.md"
{
  echo "# Video Understanding (v3) — $VID_ID"
  echo
  echo "**URL:** $URL"
  echo "**Video type:** $VIDEO_TYPE"
  echo "**Duration:** ${DURATION}s ($(printf '%02d:%02d:%02d' $((DURATION/3600)) $(((DURATION%3600)/60)) $((DURATION%60))))"
  echo "**Resolution:** $RESOLUTION"
  echo "**Transcript source:** $TRANSCRIPT_TIER"
  echo "**Frame budget:** $TARGET_FRAMES (target) / $ACTUAL_FRAMES (kept after dropping duplicates)"
  echo "**Key moments detected:** $KEY_MOMENTS"
  echo "**Frames:** $OUT/frames/ — open a frame to see it; labels: normal, dense (speaker points at visuals), scene (picture changed)"
} > "$HEADER_MD"
# One picture of ~20 frames spread over the video, to grasp it at a glance
"$PYTHON" "$SCRIPT_DIR/make-overview.py" "$OUT" >&2 || true
# Every frame, 16 per picture, so the whole video can be looked at in a few reads
"$PYTHON" "$SCRIPT_DIR/make-sheets.py" "$OUT" >&2 || true

META_ARG=()
[[ -s "$OUT/meta.json" ]] && META_ARG=(--meta "$OUT/meta.json")
if ! "$PYTHON" "$SCRIPT_DIR/build-understanding.py" "$OUT" --header "$HEADER_MD" ${META_ARG[@]+"${META_ARG[@]}"} > "$UNDERSTAND"; then
  echo "error: could not build $UNDERSTAND" >&2
  exit 1
fi
rm -f "$HEADER_MD"
echo "→ understanding:   $UNDERSTAND ($(wc -l < "$UNDERSTAND") lines)"
echo

# ─── Cleanup heavy media ────────────────────────────────────────────────────
if [[ "$KEEP_HEAVY" == "0" ]]; then
  echo "→ cleanup heavy media…"
  rm -f "$OUT"/video*.mp4 "$OUT"/video*.m4a "$OUT"/audio.m4a "$OUT"/audio.wav "$OUT"/whisper-out.* 2>/dev/null
fi
DISK_AFTER=$(du -sh "$OUT" 2>/dev/null | awk '{print $1}')
TOTAL_TIME=$(date +%s)
echo "→ workdir size:    $DISK_AFTER"
echo "→ total time:      $((TOTAL_TIME - START_TIME))s"
echo
echo "OUT_DIR=$OUT"
echo "VIDEO_TYPE=$VIDEO_TYPE"
echo "DURATION_SEC=$DURATION"
echo "TRANSCRIPT_TIER=$TRANSCRIPT_TIER"
echo "FRAME_COUNT=$ACTUAL_FRAMES"
echo "TARGET_FRAMES=$TARGET_FRAMES"
echo "KEY_MOMENTS=$KEY_MOMENTS"
echo "PLAN_JSON=$PLAN_JSON"
echo "UNDERSTANDING=$UNDERSTAND"
