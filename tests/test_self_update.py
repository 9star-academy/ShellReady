"""Self-update uses the real bootstrap with offline HTTP fixture responses."""
import os
from pathlib import Path
import subprocess
import tarfile
import unittest
import test_bootstrap as bootstrap
import test_entry_transitions as transitions

ROOT = Path(__file__).resolve().parents[1]


class SelfUpdateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = bootstrap.BootstrapTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.work = self.fixture.work
        self.prefix = self.work / 'prefix'
        (self.prefix / 'app').mkdir(parents=True)
        (self.prefix / '.shellready').touch()
        (self.prefix / 'app/old-version').write_text('original')

    def run_update(self, **env):
        script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/update.sh"
PREFIX="$TEST_PREFIX"; TARGET_USER=fixture-user
self_update
IFS= read -r remaining
printf 'REMAINING:%s\n' "$remaining"
'''
        result = subprocess.run(['bash', '-c', script], input='next-menu-input\n',
                                text=True, capture_output=True, timeout=10,
                                env={**os.environ, 'ROOT': str(ROOT), 'TEST_PREFIX': str(self.prefix),
                                     'PATH': str(self.work / 'bin') + os.pathsep + os.environ['PATH'],
                                     'FIXTURES': str(self.work), 'TMPDIR': str(self.work / 'tmp'),
                                     'SHELLREADY_REF': 'old-pinned-version', **env})
        self.assertEqual(list((self.work / 'tmp').iterdir()), [])
        return result

    def test_latest_main_snapshot_repairs_original_user_without_network_or_shell_changes(self):
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.work / 'args').read_text().splitlines(),
                         ['repair', '--user', 'fixture-user', '--skip-bbr', '--keep-shell'])
        requests = (self.work / 'requests').read_text()
        self.assertIn('/commits/main', requests)
        self.assertIn('/tar.gz/' + bootstrap.COMMIT, requests)
        self.assertIn('REMAINING:next-menu-input', result.stdout)

    def test_missing_installation_is_rejected_before_download(self):
        (self.prefix / '.shellready').unlink()
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未找到可更新', result.stderr)
        self.assertFalse((self.work / 'requests').exists())

    def test_symlink_installation_is_rejected_before_download(self):
        original = self.work / 'original-prefix'
        self.prefix.rename(original)
        self.prefix.symlink_to(original, target_is_directory=True)
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未找到可更新', result.stderr)
        self.assertFalse((self.work / 'requests').exists())

    def test_download_failures_preserve_existing_installation(self):
        for failure in ('metadata', 'archive'):
            with self.subTest(failure=failure):
                result = self.run_update(FAIL_FETCH=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.work / 'args').exists())
                self.assertEqual((self.prefix / 'app/old-version').read_text(), 'original')

    def test_partial_and_failed_repairs_keep_their_exit_codes(self):
        for code in ('1', '2'):
            with self.subTest(code=code):
                result = self.run_update(INSTALL_RC=code)
                self.assertEqual(result.returncode, int(code), result.stdout + result.stderr)
                self.assertNotIn('REMAINING:', result.stdout)


class InstalledSelfUpdateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture = transitions.EntryTransitionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.seed('atuin')
        fixture.run_cli('component', 'atuin', 'install', '--keep-shell')
        self.remote = remote = bootstrap.BootstrapTests()
        remote.setUp()
        self.addCleanup(remote.doCleanups)
        new_menu = fixture.repo / 'modules/menu.sh'
        new_menu.write_text(new_menu.read_text() + '\n# updated-menu-fixture\n')
        self.snapshot()
        flock = fixture.work / 'bin/flock'
        flock.write_text('#!/bin/sh\nprintf "lock\\n" >> "$TEST_WORK/update-locks"\nexit 0\n')
        flock.chmod(0o755)
        fixture.env.update(FIXTURES=str(remote.work), TMPDIR=str(remote.work / 'tmp'),
                           SHELLREADY_REF='old-pinned-version',
                           PATH=str(remote.work / 'bin') + os.pathsep + fixture.env['PATH'])

    def snapshot(self):
        with tarfile.open(self.remote.work / 'source.tar.gz', 'w:gz') as archive:
            archive.add(self.fixture.repo, arcname='snapshot')

    def test_installed_menu_updates_from_snapshot_with_one_lock_and_preserves_user_state(self):
        fixture, remote = self.fixture, self.remote
        disabled = fixture.prefix / 'config/disabled/atuin'
        disabled.parent.mkdir(parents=True)
        disabled.touch()
        history = fixture.home / '.local/share/atuin/history.db'
        history.parent.mkdir(parents=True)
        history.write_bytes(b'user-history-preserved')
        shell_before = (fixture.home / '.zshrc').read_bytes()
        result = fixture.run_cli(manager=True, choices='11\ny\n8\n0\n')
        self.assertEqual(result.stdout.count('ShellReady 管理菜单'), 1)
        self.assertIn('已退出旧菜单', result.stdout)
        self.assertIn('# updated-menu-fixture', (fixture.prefix / 'app/modules/menu.sh').read_text())
        self.assertTrue((fixture.prefix / 'app/bootstrap.sh').is_file())
        self.assertTrue((fixture.prefix / 'app/modules/update.sh').is_file())
        self.assertTrue(disabled.is_file())
        self.assertEqual(history.read_bytes(), b'user-history-preserved')
        self.assertEqual((fixture.home / '.zshrc').read_bytes(), shell_before)
        self.assertFalse((fixture.prefix / 'bin/starship').exists())
        self.assertFalse((fixture.prefix / 'bin/zoxide').exists())
        self.assertEqual((fixture.work / 'algo').read_text(), 'cubic')
        self.assertNotIn('-w ', (fixture.work / 'sysctl-calls').read_text())
        self.assertEqual((fixture.work / 'update-locks').read_text().splitlines(), ['lock'])
        self.assertIn('/commits/main', (remote.work / 'requests').read_text())
        self.assertEqual(list((remote.work / 'tmp').iterdir()), [])
        fixture.run_cli(manager=True, choices='0\n')

    def test_failed_extraction_returns_to_menu_without_replacing_manager(self):
        fixture, remote = self.fixture, self.remote
        tar = remote.work / 'bin/tar'
        tar.write_text('#!/bin/sh\necho "archive extraction failed" >&2\nexit 2\n')
        tar.chmod(0o755)
        before = (fixture.prefix / 'app/install.sh').read_bytes()
        result = fixture.run_cli(manager=True, choices='11\ny\n8\n0\n')
        self.assertIn('archive extraction failed', result.stderr)
        self.assertIn('更新失败（退出码 1）', result.stdout)
        self.assertNotIn('已退出旧菜单', result.stdout)
        self.assertIn('工具状态', result.stdout)
        self.assertEqual((fixture.prefix / 'app/install.sh').read_bytes(), before)
        self.assertFalse((fixture.work / 'update-locks').exists())
        self.assertEqual(list((remote.work / 'tmp').iterdir()), [])

    def test_busy_install_lock_leaves_manager_usable(self):
        fixture = self.fixture
        flock = fixture.work / 'bin/flock'
        flock.write_text('#!/bin/sh\nexit 1\n')
        before = (fixture.prefix / 'app/modules/menu.sh').read_bytes()
        result = fixture.run_cli(manager=True, choices='11\ny\n0\n')
        self.assertIn('另一个 ShellReady 安装正在运行', result.stderr)
        self.assertIn('更新失败', result.stdout)
        self.assertNotIn('更新完成', result.stdout)
        self.assertEqual((fixture.prefix / 'app/modules/menu.sh').read_bytes(), before)
        self.assertEqual(list((self.remote.work / 'tmp').iterdir()), [])
        fixture.run_cli(manager=True, choices='0\n')

    def test_failed_component_repair_does_not_report_success_and_allows_retry(self):
        fixture = self.fixture
        # A newly selected tool version requires a download; this boundary fails.
        manifest = fixture.repo / 'config/assets.tsv'
        rows = manifest.read_text().splitlines()
        for index, row in enumerate(rows):
            fields = row.split('\t')
            if fields[0] == 'atuin':
                fields[1] = '99.0.0'
                rows[index] = '\t'.join(fields)
        manifest.write_text('\n'.join(rows) + '\n')
        self.snapshot()
        result = fixture.run_cli(manager=True, choices='11\ny\n0\n')
        self.assertIn('unexpected-download', result.stderr)
        self.assertIn('更新失败', result.stdout)
        self.assertNotIn('更新完成', result.stdout)
        self.assertTrue((fixture.prefix / 'bin/atuin').is_file())
        fixture.run_cli(manager=True, choices='0\n')
        # Retry with the original manifest; the installed updater must still run.
        manifest.write_text((ROOT / 'config/assets.tsv').read_text())
        self.snapshot()
        result = fixture.run_cli('self-update', manager=True)
        self.assertIn('操作完成', result.stdout)

    def test_a_second_update_runs_through_the_newly_installed_manager(self):
        fixture = self.fixture
        for _ in range(2):
            result = fixture.run_cli(manager=True, choices='11\ny\n0\n')
            self.assertIn('更新完成', result.stdout)
            self.assertEqual(result.stdout.count('ShellReady 管理菜单'), 1)
        self.assertEqual((fixture.work / 'update-locks').read_text().splitlines(),
                         ['lock', 'lock'])
        self.assertEqual(list((self.remote.work / 'tmp').iterdir()), [])
