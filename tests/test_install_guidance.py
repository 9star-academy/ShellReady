"""Exercise real install dispatch/BBR in temp dirs; mock privilege, tools and kernel changes."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.repo = self.work / 'repo'
        self.repo.mkdir()
        shutil.copy(ROOT / 'install.sh', self.repo)
        shutil.copy(ROOT / 'bootstrap.sh', self.repo)
        for name in ('lib', 'modules'):
            shutil.copytree(ROOT / name, self.repo / name)
        entry = self.repo / 'install.sh'
        # Only privilege elevation and the host lock location are substituted;
        # real argument parsing, install ordering, BBR, summary and exit codes run.
        entry.write_text(entry.read_text().replace(
            'if [[ "$READ_ONLY" == 0 && $EUID != 0 ]]; then', 'if false; then'
        ).replace('/run/shellready', str(self.work / 'lock')))
        (self.work / 'algo').write_text('cubic')
        (self.work / 'bin').mkdir()
        flock = self.work / 'bin/flock'
        flock.write_text('#!/bin/sh\nexit 0\n')
        flock.chmod(0o755)
        with (self.repo / 'lib/common.sh').open('a') as common:
            common.write(r'''
check_platform() { ARCH=x86_64; }
resolve_user() {
    TARGET_HOME="$TEST_WORK/home"; PREFIX="$TARGET_HOME/.local/share/shellready"
    STATE="$TARGET_HOME/.local/state/shellready"
    SYSCTL_FILE="$TEST_WORK/sysctl.d/90-shellready-bbr.conf"
    BBR_STATE="$TEST_WORK/bbr-state"
    BBR_SYSCTL_DIRS=("$TEST_WORK/sysctl.d"); BBR_SYSCTL_MAIN="$TEST_WORK/sysctl.conf"
    mkdir -p "$TARGET_HOME" "${BBR_SYSCTL_DIRS[@]}"
}
prepare_user_dirs() { :; }
dpkg-query() { echo 'install ok installed'; }
sha256sum() { shasum -a 256 "$@"; }
sysctl() {
    printf '%s\n' "$*" >> "$TEST_WORK/sysctl-calls"
    case "$*" in
        '-n net.ipv4.tcp_available_congestion_control') echo "$TEST_AVAILABLE" ;;
        '-n net.ipv4.tcp_congestion_control') cat "$TEST_WORK/algo" ;;
        '-w net.ipv4.tcp_congestion_control='*)
            [[ "$TEST_DENY_WRITE" == 0 ]] || return 1
            printf '%s' "${2#*=}" > "$TEST_WORK/algo" ;;
        *) return 99 ;;
    esac
}
modprobe() { :; }
apt-get() { echo unexpected-apt >> "$TEST_WORK/calls"; return 99; }
reboot() { echo unexpected-reboot >> "$TEST_WORK/calls"; return 99; }
''')
        with (self.repo / 'modules/tools.sh').open('a') as tools:
            for name in ('install_manager', 'install_trzsz', 'install_starship',
                         'install_suggestions', 'install_atuin', 'install_zoxide'):
                tools.write(f'\n{name}() {{ echo {name} >> "$TEST_WORK/calls"; }}\n')
        with (self.repo / 'modules/shell.sh').open('a') as shell:
            shell.write('\ninstall_shell() { echo install_shell >> "$TEST_WORK/calls"; }\n')
        with (self.repo / 'modules/kernel.sh').open('a') as kernel:
            kernel.write('\ninstall_kernel() { echo unexpected-kernel >> "$TEST_WORK/calls"; return 99; }\n')

    def run_install(self, *args, available='reno cubic bbr', deny_write='0'):
        return subprocess.run(
            ['bash', str(self.repo / 'install.sh'), *args],
            env={**os.environ, 'PATH': str(self.work / 'bin') + os.pathsep + os.environ['PATH'],
                 'TEST_WORK': str(self.work), 'TEST_AVAILABLE': available,
                 'TEST_DENY_WRITE': deny_write},
            capture_output=True, text=True, timeout=10)

    def assert_no_kernel_changes(self):
        self.assertEqual((self.work / 'calls').read_text().splitlines(), [
            'install_manager', 'install_trzsz', 'install_starship',
            'install_suggestions', 'install_atuin', 'install_zoxide', 'install_shell'])

    def test_default_install_enables_existing_bbr_and_shows_optional_upgrade(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.work / 'algo').read_text(), 'bbr')
        self.assertIn('net.ipv4.tcp_congestion_control = bbr',
                      (self.work / 'sysctl.d/90-shellready-bbr.conf').read_text())
        self.assertIn('可选升级：BBRv3', result.stdout)
        self.assertIn('不保证提速', result.stdout)
        self.assertIn('重启整台服务器', result.stdout)
        self.assertIn('Ubuntu 24.04+、Debian 12+', result.stdout)
        self.assertIn("shellready bbrv3 --tag '<标准版 release tag>' --yes", result.stdout)
        self.assert_no_kernel_changes()

    def test_unsupported_bbr_shows_hint_without_claiming_enabled(self):
        result = self.run_install(available='reno cubic')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('当前内核不提供 BBR', result.stdout)
        self.assertIn('可选升级：BBRv3', result.stdout)
        self.assertNotIn('BBR 已启用', result.stdout)
        self.assertEqual((self.work / 'algo').read_text(), 'cubic')
        self.assert_no_kernel_changes()

    def test_failed_bbr_keeps_failure_without_upgrade_hint(self):
        result = self.run_install(deny_write='1')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('BBR 应用失败', result.stderr)
        self.assertNotIn('可选升级：BBRv3', result.stdout)
        self.assertEqual((self.work / 'algo').read_text(), 'cubic')
        self.assert_no_kernel_changes()

    def test_skip_bbr_keeps_tools_only_without_upgrade_hint(self):
        result = self.run_install('--skip-bbr')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('可选升级：BBRv3', result.stdout)
        self.assertFalse((self.work / 'sysctl-calls').exists())
        self.assert_no_kernel_changes()

    def test_update_does_not_repeat_initial_install_hint(self):
        result = self.run_install('update')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.work / 'algo').read_text(), 'bbr')
        self.assertNotIn('可选升级：BBRv3', result.stdout)
        self.assert_no_kernel_changes()

    def test_upgrade_still_requires_tag_and_confirmation(self):
        for args in [('bbrv3',), ('bbrv3', '--tag', 'x86_64-7.2.6'),
                     ('bbrv3', '--yes')]:
            with self.subTest(args=args):
                result = self.run_install(*args)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('必须同时指定 --tag 和 --yes', result.stderr)
                self.assertFalse((self.work / 'calls').exists())


if __name__ == '__main__':
    unittest.main()
