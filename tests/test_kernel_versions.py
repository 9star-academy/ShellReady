"""Release discovery filters standard architecture-specific tags without installing."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KernelVersionsTests(unittest.TestCase):
    def run_case(self, releases, arch='x86_64', deny=False):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'releases.json').write_text(json.dumps(releases))
            (work / 'tmp').mkdir()
            script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/kernel.sh"
download() { [[ "$DENY" == 0 ]] || return 22; cp "$FIXTURE" "$2"; }
install_kernel() { echo unexpected-install; return 99; }
kernel_release_tags
'''
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                    env={**os.environ, 'ROOT': str(ROOT), 'ARCH': arch,
                                         'FIXTURE': str(work / 'releases.json'), 'DENY': str(int(deny)),
                                         'TMPDIR': str(work / 'tmp')})
            self.assertEqual(list((work / 'tmp').iterdir()), [])
            return result

    def test_standard_versions_are_filtered_and_sorted(self):
        def release(tag, date, **extra):
            return dict(tag_name=tag, published_at=date, draft=False, prerelease=False, **extra)
        data = [release('x86_64-7.1.0', '2026-01-01'),
                release('x86_64-7.2.0-max', '2026-04-01'),
                release('arm64-7.2.0', '2026-04-01'),
                release('x86_64-7.2.0', '2026-03-01'),
                {**release('x86_64-7.3.0', '2026-05-01'), 'prerelease': True},
                {**release('x86_64-7.4.0', '2026-06-01'), 'draft': True}]
        result = self.run_case(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['x86_64-7.2.0', 'x86_64-7.1.0'])
        result = self.run_case(data, arch='aarch64')
        self.assertEqual(result.stdout.strip(), 'arm64-7.2.0')

    def test_empty_or_api_error_is_failure(self):
        for data in ([], {'message': 'API rate limit exceeded'}):
            with self.subTest(data=data):
                result = self.run_case(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('unexpected-install', result.stdout)

    def test_download_failure_cleans_temporary_files(self):
        result = self.run_case([], deny=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
