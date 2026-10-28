"""Exercise real menus/installers across successive actions with cached fake tools.

Only OS/user/package/network boundaries are replaced; the manager, component
receipts, symlinks, shared Shell setup, menus and default dispatcher are real.
"""
import os
import fcntl
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EntryTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.repo = self.work / 'repo'
        self.repo.mkdir()
        shutil.copy(ROOT / 'install.sh', self.repo)
        shutil.copy(ROOT / 'bootstrap.sh', self.repo)
        for name in ('lib', 'modules', 'config'):
            shutil.copytree(ROOT / name, self.repo / name)
        entry = self.repo / 'install.sh'
        source = entry.read_text()
        boundary = 'if [[ "$READ_ONLY" == 0 && $EUID != 0 ]]; then'
        self.assertEqual(source.count(boundary), 1)
        entry.write_text(source.replace(boundary, 'if false; then').replace(
            '/run/shellready', str(self.work / 'locks')))
        self.home = self.work / 'home'
        self.prefix = self.home / '.local/share/shellready'
        self.prefix.mkdir(parents=True)
        (self.prefix / '.shellready').touch()
        (self.work / 'sysctl.d').mkdir()
        (self.work / 'algo').write_text('cubic')
        (self.work / 'bin').mkdir()
        flock = self.work / 'bin/flock'
        flock.write_text('#!/bin/sh\nexit 0\n')
        flock.chmod(0o755)
        with (self.repo / 'lib/common.sh').open('a') as f:
            f.write(r'''
check_platform() { ARCH=x86_64; }
resolve_user() {
    TARGET_HOME="$TEST_WORK/home"; PREFIX="$TARGET_HOME/.local/share/shellready"
    STATE="$TARGET_HOME/.local/state/shellready"; LOGIN_SHELL=/bin/zsh
    SYSCTL_FILE="$TEST_WORK/sysctl.d/90-shellready-bbr.conf"; BBR_STATE="$TEST_WORK/bbr"
    BBR_SYSCTL_DIRS=("$TEST_WORK/sysctl.d"); BBR_SYSCTL_MAIN="$TEST_WORK/sysctl.conf"
    QDISC_STATE="$TEST_WORK/qdisc"; QDISC_FILE="$TEST_WORK/sysctl.d/90-shellready-fq.conf"
    KERNEL_STATE="$TEST_WORK/kernels"
}
getent() { printf '%s:x:123:123::%s:/bin/zsh\n' "$TARGET_USER" "$TARGET_HOME"; }
as_user() { env HOME="$TARGET_HOME" "$@"; }
dpkg-query() { echo 'install ok installed'; }
sha256sum() { shasum -a 256 "$@"; }
download() { echo unexpected-download >&2; return 99; }
apt-get() { echo unexpected-apt >&2; return 99; }
chsh() { echo unexpected-chsh >&2; return 99; }
reboot() { echo unexpected-reboot >&2; return 99; }
sysctl() {
    printf '%s\n' "$*" >> "$TEST_WORK/sysctl-calls"
    case "$*" in
        '-n net.ipv4.tcp_available_congestion_control') echo 'reno cubic bbr';;
        '-n net.ipv4.tcp_congestion_control') cat "$TEST_WORK/algo";;
        '-w net.ipv4.tcp_congestion_control='*) printf '%s' "${2#*=}" > "$TEST_WORK/algo";;
        *) return 99;;
    esac
}
''')
        self.env = {**os.environ, 'TEST_WORK': str(self.work),
                    'PATH': str(self.work / 'bin') + os.pathsep + os.environ['PATH']}

    def seed(self, *tools):
        for line in (self.repo / 'config/assets.tsv').read_text().splitlines():
            if not line or line.startswith('#'):
                continue
            tool, version, arch, _, digest = line.split('\t')
            if tool not in tools or arch not in ('x86_64', 'any'):
                continue
            directory = self.prefix / 'tools' / f'{tool}-{version}-{digest[:12]}'
            directory.mkdir(parents=True)
            (directory / '.complete').write_text(digest + '\n')
            binaries = ['trz', 'tsz'] if tool == 'trzsz' else [
                'zsh-autosuggestions.zsh' if tool == 'suggestions' else tool]
            for name in binaries:
                binary = directory / name
                variable = 'TOOL_' + tool.upper() + '_LOADED'
                if tool == 'suggestions':
                    binary.write_text(f'typeset -g {variable}=1\n')
                else:
                    binary.write_text('#!/bin/sh\ncase "$1" in\n'
                                      f'--version) echo "{tool} fixture";;\n'
                                      f'init) echo "typeset -g {variable}=1";;\n'
                                      'esac\n')
                binary.chmod(0o755)

    def run_cli(self, *args, choices=None, manager=False):
        command = [str(self.prefix / 'bin/shellready')] if manager else [
            'bash', str(self.repo / 'install.sh')]
        result = subprocess.run([*command, *args], input=choices, capture_output=True,
                                text=True, timeout=15, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_original_default_installs_all_and_manager_default_opens_menu(self):
        self.seed('trzsz', 'starship', 'suggestions', 'atuin', 'zoxide')
        result = self.run_cli(choices='0\n')
        self.assertNotIn('ShellReady 管理菜单', result.stdout)
        self.assertEqual((self.work / 'algo').read_text(), 'bbr')
        for binary in ('trz', 'tsz', 'starship', 'zsh-autosuggestions.zsh', 'atuin', 'zoxide'):
            self.assertTrue((self.prefix / 'bin' / binary).is_symlink(), binary)
        result = self.run_cli(choices='2\n1\n0\n0\n', manager=True)
        # Queue inspection may be unavailable on this host; the menu stays usable.
        self.assertIn('ShellReady 管理菜单', result.stdout)
        self.assertIn('BBR 网络管理', result.stdout)
        self.assertEqual((self.work / 'algo').read_text(), 'bbr')

    def test_default_and_explicit_install_do_not_enter_menu_even_with_a_color_terminal(self):
        self.seed('trzsz', 'starship', 'suggestions', 'atuin', 'zoxide')
        with (self.repo / 'modules/menu.sh').open('a') as menu:
            for name in ('menu_choose', 'menu_style', 'menu_snapshot', 'menu_dimensions'):
                menu.write(f'\n{name}() {{ echo unexpected-menu >> "$TEST_WORK/menu-calls"; return 99; }}\n')
        for args in ((), ('install',)):
            with self.subTest(args=args):
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 34, 100, 0, 0))
                process = subprocess.Popen(['bash', str(self.repo / 'install.sh'), *args],
                                           stdin=slave, stdout=slave, stderr=slave,
                                           env={**self.env, 'TERM': 'xterm-256color',
                                                'COLORTERM': 'truecolor'})
                output = b''
                sent_exit = False
                deadline = time.monotonic() + 15
                try:
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], 0.05)[0]:
                            output += os.read(master, 65536)
                            if not sent_exit and '正在进入'.encode() in output:
                                os.write(master, b'exit\n')
                                sent_exit = True
                        elif process.poll() is not None:
                            break
                    process.wait(timeout=1)
                    self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=4)
                    os.close(master)
                    os.close(slave)
                installer_output = output.decode().split('正在进入', 1)[0]
                self.assertNotIn('\x1b', installer_output)
                self.assertTrue(sent_exit, output.decode())
                self.assertNotIn('请选择', output.decode())
                self.assertFalse((self.work / 'menu-calls').exists())
                self.assertEqual((self.work / 'algo').read_text(), 'bbr')
                for name in ('trz', 'tsz', 'starship', 'zsh-autosuggestions.zsh', 'atuin', 'zoxide'):
                    self.assertTrue((self.prefix / 'bin' / name).is_symlink(), name)

    def test_menu_disable_then_legacy_update_preserves_component_switch(self):
        self.seed('trzsz', 'starship', 'suggestions', 'atuin', 'zoxide')
        self.run_cli()
        self.run_cli('menu', choices='6\n3\n0\n0\n')
        self.run_cli('update')
        self.assertTrue((self.prefix / 'config/disabled/atuin').is_file())
        result = subprocess.run(['zsh', '-dfi', '-c',
                                 'source "$HOME/.local/share/shellready/config/init.zsh"; '
                                 '[[ -z ${TOOL_ATUIN_LOADED:-} && ${TOOL_STARSHIP_LOADED:-} == 1 '
                                 '&& ${TOOL_ZOXIDE_LOADED:-} == 1 ]]'],
                                input='', capture_output=True, text=True,
                                env={**self.env, 'HOME': str(self.home)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_single_install_remove_and_repair_do_not_add_other_tools(self):
        self.seed('atuin')
        self.run_cli('component', 'atuin', 'install')
        self.assertTrue((self.prefix / 'bin/atuin').is_symlink())
        self.assertFalse((self.prefix / 'bin/starship').exists())
        self.assertEqual((self.work / 'algo').read_text(), 'cubic')
        self.run_cli('component', 'atuin', 'remove')
        self.run_cli('repair', '--skip-bbr')
        self.assertFalse((self.prefix / 'bin/atuin').exists())
        self.assertFalse((self.prefix / 'bin/starship').exists())
        self.assertTrue((self.prefix / 'config/atuin/config.toml').is_file())

    def test_one_click_keeps_existing_fq_and_network_restore_keeps_tools(self):
        self.seed('trzsz', 'starship', 'suggestions', 'atuin', 'zoxide')
        fq = self.work / 'sysctl.d/90-shellready-fq.conf'
        original_fq = '# Managed by ShellReady\nnet.core.default_qdisc = fq\n'
        fq.write_text(original_fq)
        self.run_cli()
        self.assertEqual(fq.read_text(), original_fq)
        self.assertNotIn('default_qdisc', (self.work / 'sysctl-calls').read_text())
        # No queue transaction was created by default installation.
        fq.unlink()
        self.run_cli('menu', choices='2\n5\ny\n0\n0\n')
        self.assertEqual((self.work / 'algo').read_text(), 'cubic')
        self.assertTrue((self.prefix / 'bin/atuin').is_symlink())
        self.run_cli()
        self.assertEqual((self.work / 'algo').read_text(), 'bbr')
