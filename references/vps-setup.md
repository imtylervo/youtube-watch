# Running youtube-watch on a Linux VPS (with proxy)

A datacenter/VPS IP usually gets YouTube's "Sign in to confirm you're not a bot"
block. This guide covers the Linux dependencies and the on-demand proxy setup so
the skill works headless.

## 1. System + Python dependencies

```bash
# system
sudo apt-get install -y ffmpeg          # required (frames, overview.jpg); >= 5.1 recommended
# optional: tesseract (--ocr):
#   sudo apt-get install -y tesseract-ocr tesseract-ocr-vie

# Python (user-site; works around Debian's PEP 668 "externally-managed").
# If pip is missing:  curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3 - --user --break-system-packages
python3 -m pip install --user --break-system-packages \
    yt-dlp youtube-transcript-api requests curl_cffi pysocks
# Audio fallback (faster-whisper, the only Tier C on Linux): install into the skill's own venv
#   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt yt-dlp requests curl_cffi pysocks
#   (the large-v3-turbo model, ~1.6 GB, downloads on first use; --whisper-model small is lighter on a CPU-only VPS)
# YouTube also needs a JavaScript runtime for yt-dlp: deno, or node (the script passes --js-runtimes node when only node exists).
```

**Important — install `yt-dlp` via pip, not the standalone binary.** The
standalone `yt-dlp` zipapp cannot talk to an HTTPS proxy (it errors:
`To use an HTTPS proxy for this request, one of the following dependencies needs
to be installed: requests, curl_cffi`). The pip install runs under the same
Python that has `requests`/`curl_cffi`, which register the HTTPS-proxy-capable
request handlers. `requests` must be reasonably recent (>= 2.32); older versions
are reported by yt-dlp as `(unsupported)` and ignored.

Make sure `~/.local/bin` is ahead of any other `yt-dlp` on `PATH`.

## 2. Proxy config (on-demand)

The scripts try a **direct** connection first and only switch to the proxy if the
first request is blocked (`maybe_enable_proxy`). The proxy is exported only inside
the running script — never globally, so it doesn't touch your other traffic.

```bash
cp yt-watch.env.example ~/.config/yt-watch.env
chmod 600 ~/.config/yt-watch.env
# edit it and put in real credentials
```

### Example: NordVPN HTTPS proxy

- **Port 89.**
- Username/password = NordVPN **service credentials** (dashboard → *Set up
  NordVPN manually* → *Service credentials*), not the account login.
- Address servers as `<server>.proxy.nordvpn.com` — the proxy presents a
  `*.proxy.nordvpn.com` certificate, so `<server>.nordvpn.com` fails cert
  verification.
- Find a proxy-capable server (country_id 228 = US):

```bash
curl -s "https://api.nordvpn.com/v1/servers/recommendations?filters%5Bservers_technologies%5D%5Bidentifier%5D=proxy_ssl&filters%5Bcountry_id%5D=228&limit=5" \
  | python3 -c "import sys,json;[print(s['hostname'],'load',s['load']) for s in json.load(sys.stdin)]"
```

Then set in `~/.config/yt-watch.env`:

```bash
export YT_PROXY="https://SERVICE_USER:SERVICE_PASS@us8502.proxy.nordvpn.com:89"
```

If the pinned server goes down, re-run the curl above and swap the hostname.

Any HTTP(S) or SOCKS5 proxy works the same way. A flat-rate VPN proxy suits video
downloads better than a residential proxy billed per GB.

## 3. Test

```bash
scripts/extract-v3.sh "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --quality fast --max-frames 20
# direct first; if blocked you'll see "→ direct connection blocked — routing through proxy"
# success = transcript.txt + frames/ + overview.jpg + understanding.md under ~/.cache/yt-watch/<id>/
```

Run the test suite after pulling an update (needs `ffmpeg`; no network):

```bash
python3 -m unittest discover tests
```

## Notes

- Without faster-whisper in the skill's `.venv` there is no audio fallback: the script says
  so and works from subtitles only.

- Credentials live only in `~/.config/yt-watch.env` (chmod 600), outside this
  repo. Never commit them. `yt-watch.env` is gitignored.
- The transcript path (`youtube-transcript-api`) often works direct even when
  yt-dlp is blocked, because it hits a different endpoint.
