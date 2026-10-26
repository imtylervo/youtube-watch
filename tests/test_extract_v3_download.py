"""Exercise the real Stage 4 download boundary without network or frame extraction."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
FAKE_YTDLP = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['YTDLP_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
output = Path(args[args.index('-o') + 1].replace('%(ext)s', 'mp4'))
mode = os.environ['YTDLP_MODE']
android = 'youtube:player_client=android' in args
embedded = 'youtube:player_client=web_embedded' in args
if mode == 'default-success' and not android:
    output.write_bytes(b'complete default video')
    sys.exit(0)
if mode == 'recover-embedded' and embedded:
    output.write_bytes(b'complete embedded video')
    sys.exit(0)
if mode == 'recover-403' and android:
    output.write_bytes(b'complete progressive video')
    sys.exit(0)
output.with_name('video.f248.mp4').write_bytes(b'incomplete dash')
print('ERROR: HTTP Error 403: Forbidden', file=sys.stderr)
sys.exit(1)
'''


class DownloadTests(unittest.TestCase):
    def run_case(self, mode, url='https://www.youtube.com/watch?v=test'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake = root / 'yt-dlp'
            fake.write_text(FAKE_YTDLP)
            fake.chmod(0o755)
            out = root / 'out'
            out.mkdir()
            source = (REPO / 'scripts/extract-v3.sh').read_text()
            # Use the production block so regressions in exit status/selection are caught.
            start = source.index('echo "→ Stage 4:')
            end = source.index('EXTRACTOR=', start)
            block = source[start:end]
            preamble = 'set -uo pipefail\nMAX_HEIGHT=480\n'
            # Include the production client args and URL classifier.
            preamble += '\n'.join(line for line in source.splitlines()
                                  if line.startswith(('YTDLP_YOUTUBE_CLIENT_ARGS=', 'YTDLP_EMBEDDED_CLIENT_ARGS='))) + '\n'
            fn_start = source.index('is_youtube_url()')
            fn_end = source.index('\n}\n', fn_start) + 3
            preamble += source[fn_start:fn_end] + '\n'
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}',
                       OUT=str(out), URL=url, YTDLP_LOG=str(root/'calls'), YTDLP_MODE=mode)
            result = subprocess.run(['bash', '-c', preamble + block],
                                    env=env, text=True, capture_output=True, timeout=10)
            calls = [json.loads(line) for line in (root/'calls').read_text().splitlines()]
            artifacts = {p.name: p.read_bytes() for p in out.glob('*.mp4')}
            return result, calls, artifacts

    def test_default_success_keeps_quality_and_skips_fallback(self):
        result, calls, artifacts = self.run_case('default-success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('youtube:player_client=android', calls[0])
        self.assertIn('bestvideo[height<=480]', calls[0][calls[0].index('-f')+1])
        self.assertEqual(artifacts['video.mp4'], b'complete default video')

    def test_youtube_403_recovers_once_with_android_progressive(self):
        result, calls, artifacts = self.run_case('recover-403')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 3)  # default, embedded, android
        self.assertNotIn('youtube:player_client=android', calls[0])
        self.assertIn('youtube:player_client=web_embedded', calls[1])
        self.assertIn('youtube:player_client=android', calls[2])
        # Fallback keeps the requested height cap; 360p format 18 is only the last resort.
        self.assertEqual(calls[2][calls[2].index('-f')+1],
                         'best[height<=480][ext=mp4]/best[height<=480]/18')
        self.assertIn(b'complete progressive video', artifacts.values())
        self.assertNotIn('video saved:     ' + 'video.f248.mp4', result.stdout)

    def test_youtube_403_recovers_with_embedded_client_at_requested_height(self):
        result, calls, artifacts = self.run_case('recover-embedded')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)  # the android 360p fallback is never reached
        self.assertIn('youtube:player_client=web_embedded', calls[1])
        self.assertIn('bestvideo[height<=480]', calls[1][calls[1].index('-f')+1])
        self.assertEqual(artifacts['video.mp4'], b'complete embedded video')

    def test_total_failure_rejects_existing_partial_dash_file(self):
        result, calls, artifacts = self.run_case('fail-fragment')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 3)
        self.assertIn('video.f248.mp4', artifacts)
        self.assertNotIn('video saved:', result.stdout)

    def test_non_youtube_failure_does_not_retry_android(self):
        result, calls, _ = self.run_case('fail-fragment', 'https://example.com/video.mp4')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('youtube:player_client=android', calls[0])


if __name__ == '__main__':
    unittest.main()
