"""Real downloader and tool validation with offline transport boundaries."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MIRROR = 'https://mirror.example'
RAW = 'https://raw.githubusercontent.com/owner/repo/' + 'a' * 40 + '/file.zsh'
API = 'https://api.github.com/repos/owner/repo/releases?per_page=100'
RELEASE = 'https://github.com/owner/repo/releases/download/v1/tool.tar.gz'


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def run_download(self, url, mode='auto', body='', **env):
        script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
WORK="$TEST_WORK"; ARCH=x86_64
curl() {
    local url='' dest=''
    while (($#)); do
        case "$1" in https://*) url=$1; shift;; -o) dest=$2; shift 2;; *) shift;; esac
    done
    printf '%s\n' "$url" >> "$WORK/requests"
    printf partial > "$dest"
    [[ "$url" != "${FAIL_URL:-}" && "${FAIL_ALL:-0}" != 1 ]] || return 22
    [[ "${FAIL_GATEWAY:-0}" != 1 || "$url" != https://gh-api.p3terx.com/* ]] || return 22
    [[ "${BLOCK_ORIGIN:-0}" != 1 || "$url" == https://mirror.example/* || "$url" == https://cdn.jsdelivr.net/* || "$url" == https://gh-api.p3terx.com/* ]] || return 28
    printf payload > "$dest"
}
''' + (body or 'download "$TEST_URL" "$WORK/file"')
        return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                              env={**os.environ, 'ROOT': str(ROOT), 'TEST_WORK': str(self.work),
                                   'TEST_URL': url, 'SHELLREADY_DOWNLOAD_MODE': mode,
                                   'SHELLREADY_GITHUB_MIRROR': MIRROR, **env}, timeout=5)

    def requests(self):
        path = self.work / 'requests'
        return path.read_text().splitlines() if path.exists() else []

    def test_auto_uses_origin_first_and_mirror_after_failure(self):
        result = self.run_download(RELEASE, FAIL_URL=RELEASE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests(), [RELEASE, MIRROR + '/' + RELEASE])
        self.assertEqual((self.work / 'file').read_text(), 'payload')

    def test_cn_api_and_release_work_without_origin_access(self):
        for url in (API, RELEASE):
            with self.subTest(url=url):
                (self.work / 'requests').unlink(missing_ok=True)
                result = self.run_download(url, mode='cn', BLOCK_ORIGIN='1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.requests(), [MIRROR + '/' + url])

    def test_cn_raw_uses_jsdelivr_with_same_commit(self):
        result = self.run_download(RAW, mode='cn', BLOCK_ORIGIN='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests(), ['https://cdn.jsdelivr.net/gh/owner/repo@' + 'a' * 40 + '/file.zsh'])

    def test_cn_raw_falls_back_to_custom_mirror_then_origin(self):
        cdn = 'https://cdn.jsdelivr.net/gh/owner/repo@' + 'a' * 40 + '/file.zsh'
        result = self.run_download(RAW, mode='cn', FAIL_URL=cdn)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests(), [cdn, MIRROR + '/' + RAW])

    def test_archive_mirror_uses_supported_github_archive_url(self):
        url = 'https://codeload.github.com/owner/repo/tar.gz/' + 'a' * 40
        result = self.run_download(url, mode='cn')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests(), [MIRROR + '/https://github.com/owner/repo/archive/' + 'a' * 40 + '.tar.gz'])

    def test_direct_never_uses_mirrors(self):
        result = self.run_download(RELEASE, mode='direct', FAIL_URL=RELEASE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests(), [RELEASE])

    def test_cn_api_uses_dedicated_gateway_after_mirror_rate_limit(self):
        result = self.run_download(API, mode='cn', FAIL_URL=MIRROR + '/' + API, BLOCK_ORIGIN='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests(), [MIRROR + '/' + API,
                                         'https://gh-api.p3terx.com/repos/owner/repo/releases?per_page=100'])

    def test_cn_can_fall_back_to_origin(self):
        result = self.run_download(RELEASE, mode='cn', FAIL_URL=MIRROR + '/' + RELEASE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests(), [MIRROR + '/' + RELEASE, RELEASE])

    def test_cn_api_can_fall_back_to_origin_after_all_mirrors_fail(self):
        result = self.run_download(API, mode='cn', FAIL_URL=MIRROR + '/' + API, FAIL_GATEWAY='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests()[-1], API)

    def test_failure_keeps_valid_file_and_removes_partial_file(self):
        (self.work / 'file').write_text('original')
        result = self.run_download(RELEASE, FAIL_ALL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.work / 'file').read_text(), 'original')
        self.assertFalse((self.work / 'file.part').exists())

    def test_invalid_config_fails_before_network_access(self):
        for env in ({'SHELLREADY_DOWNLOAD_MODE': 'invalid'},
                    {'SHELLREADY_GITHUB_MIRROR': 'http://mirror.example'},
                    {'SHELLREADY_GITHUB_MIRROR': 'https://user:secret@mirror.example'},
                    {'SHELLREADY_GITHUB_MIRROR': 'https://mirror.example/$(touch nope)'}):
            with self.subTest(env=env):
                result = self.run_download(API, **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.requests(), [])

    def test_unrelated_domains_and_plain_http_are_not_mirrored(self):
        for url in ('https://example.com/file', 'https://github.com.evil.example/file'):
            (self.work / 'requests').unlink(missing_ok=True)
            result = self.run_download(url, mode='cn')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.requests(), [url])
        (self.work / 'requests').unlink()
        self.assertNotEqual(self.run_download('http://example.com/file').returncode, 0)
        self.assertEqual(self.requests(), [])

    def test_mirror_payload_still_requires_fixed_tool_hash(self):
        config = self.work / 'config'
        config.mkdir()
        expected = hashlib.sha256(b'expected').hexdigest()
        (config / 'assets.tsv').write_text(f'suggestions\t1\tany\t{RAW}\t{expected}\n')
        result = self.run_download(RAW, mode='cn', body=r'''
source "$ROOT/modules/tools.sh"
ROOT="$WORK"; PREFIX="$WORK/prefix"
mkdir -p "$PREFIX/bin"
as_user() { "$@"; }
install_tool suggestions
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 不匹配', result.stderr)
        self.assertFalse((self.work / 'prefix/bin/zsh-autosuggestions.zsh').exists())
        self.assertTrue(self.requests()[0].startswith('https://cdn.jsdelivr.net/'))

    def test_wget_uses_same_mirror_policy_without_curl(self):
        result = self.run_download(RELEASE, mode='cn', body=r'''
command() {
    if [[ "$*" == '-v curl' ]]; then return 1; fi
    builtin command "$@"
}
wget() {
    local dest='' url=''
    while (($#)); do
        case "$1" in -O) dest=$2; shift 2;; https://*) url=$1; shift;; *) shift;; esac
    done
    printf '%s\n' "$url" >> "$WORK/requests"
    printf payload > "$dest"
}
download "$TEST_URL" "$WORK/file"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests(), [MIRROR + '/' + RELEASE])


if __name__ == '__main__':
    unittest.main()
