"""Exercise the remote entry with local HTTP fixtures; never install on the host."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        (self.work / "bin").mkdir()
        (self.work / "tmp").mkdir()
        self.metadata = self.work / "commit.json"
        self.metadata.write_text('{\n  "sha": "' + COMMIT + '",\n  "files": []\n}\n')
        entry = b'#!/bin/bash\nprintf "%s\\n" "$@" > "$FIXTURES/args"\nexit "${INSTALL_RC:-0}"\n'
        with tarfile.open(self.work / "source.tar.gz", "w:gz", pax_headers={'comment': COMMIT}) as archive:
            info = tarfile.TarInfo("snapshot/install.sh")
            info.size = len(entry)
            archive.addfile(info, io.BytesIO(entry))
        curl = self.work / "bin/curl"
        curl.write_text('''#!/bin/bash
set -eu
url=''; dest=''
while (($#)); do
    case "$1" in
        https://*) url=$1; shift ;;
        -o) dest=$2; shift 2 ;;
        *) shift ;;
    esac
done
printf '%s\n' "$url" >> "$FIXTURES/requests"
if [[ "$url" == https://mirror.example/* ]]; then
    [[ ${FAIL_FETCH:-} != mirror ]] || exit 22
    url=${url#https://mirror.example/}
elif [[ ${BLOCK_ORIGIN:-0} == 1 ]]; then
    exit 28
fi
case "$url" in
    https://api.github.com/*)
        [[ ${FAIL_FETCH:-} != metadata ]] || exit 22
        cp "$FIXTURES/commit.json" "$dest" ;;
    https://codeload.github.com/*|https://github.com/*/archive/*)
        [[ ${FAIL_FETCH:-} != archive ]] || exit 22
        cp "$FIXTURES/source.tar.gz" "$dest" ;;
    *) exit 99 ;;
esac
''')
        curl.chmod(0o755)

    def run_entry(self, *args, **env):
        result = subprocess.run(
            ["bash", "-c", 'bash <(cat "$1") "${@:2}"', "bash", str(ROOT / "bootstrap.sh"), *args],
            env={**os.environ, "PATH": str(self.work / "bin") + os.pathsep + os.environ["PATH"],
                 "FIXTURES": str(self.work), "TMPDIR": str(self.work / "tmp"), "SHELLREADY_REF": "main",
                 "SHELLREADY_DOWNLOAD_MODE": "direct", "SHELLREADY_GITHUB_MIRROR": "https://mirror.example", **env},
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(list((self.work / "tmp").iterdir()), [], "bootstrap temporary files leaked")
        return result

    def test_process_substitution_forwards_args_and_pending_status(self):
        p = self.run_entry("--user", "test-user", "--skip-bbr", INSTALL_RC="2")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual((self.work / "args").read_text().splitlines(), ["--user", "test-user", "--skip-bbr"])
        self.assertIn("/tar.gz/" + COMMIT, (self.work / "requests").read_text())

    def test_default_and_menu_entry_are_forwarded_without_inventing_an_action(self):
        for args in ((), ('menu',)):
            with self.subTest(args=args):
                result = self.run_entry(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((self.work / 'args').read_text().split(), list(args))

    def test_large_commit_response_does_not_abort_with_sigpipe(self):
        self.metadata.write_text('{\n  "sha": "' + COMMIT + '",\n  "files": [\n' +
                                 ('    {\n      "sha": "' + "b" * 40 + '",\n      "filename": "fixture"\n    },\n') * 10000 + ']\n}\n')
        p = self.run_entry("--help")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((self.work / "args").read_text(), "--help\n")

    def test_metadata_failure_never_runs_installer(self):
        p = self.run_entry(FAIL_FETCH="metadata")
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.work / "args").exists())
        self.assertEqual(len((self.work / "requests").read_text().splitlines()), 1)

    def test_archive_failure_never_runs_installer(self):
        p = self.run_entry(FAIL_FETCH="archive")
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.work / "args").exists())

    def test_extraction_failure_is_not_reported_as_partial_installation(self):
        tar = self.work / 'bin/tar'
        tar.write_text('#!/bin/sh\necho "archive extraction failed" >&2\nexit 2\n')
        tar.chmod(0o755)
        p = self.run_entry()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('archive extraction failed', p.stderr)
        self.assertFalse((self.work / 'args').exists())

    def test_download_exit_two_is_not_reported_as_partial_installation(self):
        curl = self.work / 'bin/curl'
        curl.write_text('#!/bin/sh\necho "download failed" >&2\nexit 2\n')
        p = self.run_entry()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse((self.work / 'args').exists())

    def test_invalid_commit_never_downloads_archive(self):
        self.metadata.write_text('{"message": "API rate limit exceeded"}\n')
        p = self.run_entry()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("无法解析 commit", p.stderr)
        self.assertFalse((self.work / "args").exists())
        self.assertEqual(len((self.work / "requests").read_text().splitlines()), 1)

    def test_custom_ref_and_failed_install_are_preserved(self):
        p = self.run_entry(SHELLREADY_REF="v0.1.0", INSTALL_RC="1")
        self.assertEqual(p.returncode, 1)
        self.assertIn("/commits/v0.1.0", (self.work / "requests").read_text())

    def test_cn_snapshot_does_not_need_commit_api_or_origin(self):
        p = self.run_entry('--help', SHELLREADY_DOWNLOAD_MODE='cn', BLOCK_ORIGIN='1')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(COMMIT, p.stdout)
        self.assertEqual((self.work / 'args').read_text(), '--help\n')
        self.assertEqual((self.work / 'requests').read_text().splitlines(),
                         ['https://mirror.example/https://github.com/9star-academy/ShellReady/archive/main.tar.gz'])

    def test_auto_uses_archive_commit_when_api_is_rate_limited(self):
        p = self.run_entry(SHELLREADY_DOWNLOAD_MODE='auto', FAIL_FETCH='metadata')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(COMMIT, p.stdout)

    def test_cn_ref_archive_without_commit_metadata_is_not_executed(self):
        with tarfile.open(self.work / 'source.tar.gz', 'w:gz') as archive:
            info = tarfile.TarInfo('snapshot/install.sh')
            info.size = 0
            archive.addfile(info, io.BytesIO(b''))
        p = self.run_entry(SHELLREADY_DOWNLOAD_MODE='cn')
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.work / 'args').exists())

    def test_pinned_commit_needs_no_api(self):
        p = self.run_entry(SHELLREADY_DOWNLOAD_MODE='cn', SHELLREADY_REF=COMMIT)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn('/commits/', (self.work / 'requests').read_text())
        self.assertIn('/archive/' + COMMIT, (self.work / 'requests').read_text())

    def test_wrong_archive_commit_is_not_executed(self):
        p = self.run_entry(SHELLREADY_DOWNLOAD_MODE='cn', SHELLREADY_REF='b' * 40)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('commit 与请求版本不符', p.stderr)
        self.assertFalse((self.work / 'args').exists())


if __name__ == "__main__":
    unittest.main()
