"""The default output folder must be unique per video, also for sites whose file names repeat."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
FAKE_YTDLP = '#!/bin/sh\necho "HLSPlaylist|NA|62"\n'


class OutputDirTests(unittest.TestCase):
    def out_dir_for(self, url, fake_ytdlp=FAKE_YTDLP):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake = root / 'yt-dlp'
            fake.write_text(fake_ytdlp)
            fake.chmod(0o755)
            source = (REPO / 'scripts/extract-v3.sh').read_text()
            start = source.index('video_meta() {')
            end = source.index('mkdir -p "$OUT/frames"', start)
            script = 'set -uo pipefail\nOUT=""\nLOCAL_FILE=""\nmaybe_enable_proxy() { :; }\n' + source[start:end] + 'echo "$OUT"\n'
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}', URL=url, HOME=str(root))
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return Path(result.stdout.strip()).name

    def test_reddit_video_folder_uses_its_id(self):
        self.assertEqual(self.out_dir_for('https://v.redd.it/t17eu5x2tlth1/HLSPlaylist.m3u8'), 'vreddit-t17eu5x2tlth1')

    def test_other_sites_keep_the_yt_dlp_id(self):
        self.assertEqual(self.out_dir_for('https://example.com/HLSPlaylist.m3u8'), 'HLSPlaylist')

    def test_blocked_metadata_takes_the_id_from_the_youtube_url(self):
        # yt-dlp prints nothing (bot check): parallel runs must not all land in "video/"
        blocked = '#!/bin/sh\nexit 1\n'
        self.assertEqual(self.out_dir_for('https://www.youtube.com/watch?v=14Vm0CiyUVE', blocked), '14Vm0CiyUVE')
        self.assertEqual(self.out_dir_for('https://youtu.be/OINK1lURm4w?t=3', blocked), 'OINK1lURm4w')
        self.assertEqual(self.out_dir_for('https://www.youtube.com/shorts/EqPVudVkS2w', blocked), 'EqPVudVkS2w')


if __name__ == '__main__':
    unittest.main()
