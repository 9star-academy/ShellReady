"""Warm menus: real Bash reader/rendering in a PTY, isolated action boundaries."""
import errno
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unicodedata
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/components.sh"
source "$ROOT/modules/menu.sh"
TARGET_USER=fixture; PREFIX="$HOME/prefix"; KEEP_SHELL=1; SKIP_BBR=0
PRETTY_NAME='Ubuntu 24.04 LTS'; ARCH=x86_64
sysctl() {
    case "$*" in
        '-n net.ipv4.tcp_congestion_control') echo bbr ;;
        '-n net.core.default_qdisc') echo fq ;;
        *) echo unexpected-write >&2; return 99 ;;
    esac
}
menu_action() { printf '\nCALL:%s\n' "$*"; }
component_status() { echo 'fixture 已安装'; }
"$ENTRY"
'''
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


class MenuScreen:
    """Minimal VT screen for the CR/LF, cursor-up and erase used by this menu."""
    def __init__(self, columns=100, rows=34):
        self.columns, self.rows = columns, rows
        self.cells = [[' '] * columns for _ in range(rows)]
        self.row = self.column = 0

    def feed(self, output):
        tokens = re.finditer(r'\x1b\[([0-9;?]*)([A-Za-z])|([\s\S])', output)
        for token in tokens:
            params, command, char = token.groups()
            if command:
                count = int(params or '1') if params.isdigit() or not params else 1
                if command == 'A':
                    self.row = max(0, self.row - count)
                elif command == 'K':
                    self.cells[self.row][self.column:] = [' '] * (self.columns - self.column)
                continue
            if char == '\r':
                self.column = 0
            elif char == '\n':
                self.down()
            else:
                width = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
                if self.column + width > self.columns:
                    self.column = 0
                    self.down()
                self.cells[self.row][self.column] = char
                if width == 2:
                    self.cells[self.row][self.column + 1] = ''
                self.column += width

    def down(self):
        self.row += 1
        if self.row == self.rows:
            self.cells.pop(0)
            self.cells.append([' '] * self.columns)
            self.row -= 1

    def prompt(self):
        return next(''.join(row).rstrip() for row in reversed(self.cells)
                    if ''.join(row).startswith('请选择'))


class MenuStyleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = {**os.environ, 'ROOT': str(ROOT), 'HOME': str(self.home),
                    'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'ENTRY': 'main_menu'}
        self.env.pop('NO_COLOR', None)

    def pipe(self, choices='0\n', **env):
        return subprocess.run(['bash', '-c', SCRIPT], input=choices, capture_output=True,
                              text=True, timeout=5, env={**self.env, **env})

    def terminal(self, rows=34, columns=100, script=SCRIPT, controlling_session=False, **env):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
        before = termios.tcgetattr(slave)
        def new_session():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        command = [sys.executable, '-c', script] if controlling_session else ['bash', '-c', script]
        process = subprocess.Popen(command, stdin=slave, stdout=slave,
                                   stderr=slave, env={**self.env, **env},
                                   preexec_fn=new_session if controlling_session else None)
        def cleanup():
            if process.poll() is None:
                if controlling_session:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            process.wait(timeout=4)
            os.close(master)
            os.close(slave)
        self.addCleanup(cleanup)
        return process, master, slave, before

    def receive(self, process, master, marker='请选择', timeout=4):
        data = b''
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                data += chunk
                if marker.encode() in data and not select.select([master], [], [], 0.03)[0]:
                    return data.decode(errors='replace')
            elif process.poll() is not None:
                break
        output = data.decode(errors='replace')
        self.assertIn(marker, output, output)
        return output

    def send(self, terminal, keys, marker='请选择'):
        process, master, _, _ = terminal
        os.write(master, keys)
        return self.receive(process, master, marker)

    def finish(self, terminal, keys=b'0\n'):
        process, master, slave, before = terminal
        os.write(master, keys)
        # Drain PTY output while waiting: a redraw can exceed its kernel buffer.
        deadline = time.monotonic() + 4
        output = b''
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                output += os.read(master, 65536)
        process.wait(timeout=4)
        self.assertEqual(process.returncode, 0)
        after = termios.tcgetattr(slave)
        self.assertEqual(after[3] & (termios.ECHO | termios.ICANON),
                         before[3] & (termios.ECHO | termios.ICANON))
        self.assertNotIn(b'CALL:install', output)

    def test_pipe_keeps_numbers_and_has_no_terminal_escape_codes(self):
        result = self.pipe('2\n1\n0\n8\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('\x1b', result.stdout)
        self.assertIn('CALL:bbr-status', result.stdout)
        self.assertIn('CALL:status', result.stdout)
        self.assertNotIn('CALL:install', result.stdout)
        self.assertIn('一键配置', result.stdout)
        self.assertIn('功能管理', result.stdout)
        self.assertIn('默认队列', result.stdout)

    def test_both_menus_use_b2_cream_selection_and_live_bbr_summary(self):
        for entry in ('main_menu', 'bbr_menu'):
            with self.subTest(entry=entry):
                terminal = self.terminal(ENTRY=entry)
                output = self.receive(*terminal[:2])
                self.assertIn('\x1b[38;2;241;198;94m', output)
                self.assertIn('\x1b[38;2;255;240;207m', output)
                self.assertIn('\x1b[48;2;81;68;53m', output)
                self.assertNotIn('CALL:', output)
                if entry == 'bbr_menu':
                    plain = ANSI.sub('', output)
                    self.assertIn('TCP 算法：bbr', plain)
                    self.assertIn('默认队列：fq', plain)
                self.finish(terminal)

    def test_typing_selects_bbr_without_action_until_enter(self):
        terminal = self.terminal()
        self.receive(*terminal[:2])
        output = self.send(terminal, b'2')
        plain = ANSI.sub('', output)
        self.assertRegex(plain, r'>\s+2\. BBR 网络管理')
        self.assertNotIn('CALL:', output)
        output = self.send(terminal, b'\n')
        self.assertIn('BBR 网络管理', output)
        self.assertNotIn('CALL:', output)
        output = self.send(terminal, b'1\n')
        # A key redraw can arrive before Enter is processed.
        if 'CALL:bbr-status' not in output:
            output += self.receive(*terminal[:2], marker='CALL:bbr-status')
        self.assertIn('CALL:bbr-status', output)
        self.finish(terminal, b'0\n0\n')

    def test_arrows_and_multidigit_uninstall_keep_confirmation(self):
        terminal = self.terminal()
        self.receive(*terminal[:2])
        output = self.send(terminal, b'\x1b[A')
        self.assertRegex(ANSI.sub('', output), r'>\s+10\. 卸载 ShellReady')
        self.send(terminal, b'\n', '[y/N]')
        output = self.send(terminal, b'n\n')
        self.assertNotIn('CALL:', output)
        self.send(terminal, b'10\n', '[y/N]')
        output = self.send(terminal, b'n\n')
        self.assertNotIn('CALL:', output)
        output = self.send(terminal, b'\x1bOB')
        self.assertRegex(ANSI.sub('', output), r'>\s+1\. 一键安装')
        self.assertNotIn('CALL:', output)
        output = self.send(terminal, b'\x1bOA')
        self.assertRegex(ANSI.sub('', output), r'>\s+0\. 退出')
        self.finish(terminal)

    def test_backspace_changes_choice_and_unsupported_escape_does_not_install(self):
        terminal = self.terminal()
        self.receive(*terminal[:2])
        self.send(terminal, b'1')
        output = self.send(terminal, b'\x7f')
        self.assertNotRegex(ANSI.sub('', output), r'>\s+1\. ')
        output = self.send(terminal, b'\x1b[C')
        self.assertNotIn('CALL:', output)
        self.finish(terminal, b'\n')

    def test_backspace_erases_the_old_digit_on_the_visible_screen(self):
        terminal = self.terminal()
        screen = MenuScreen()
        screen.feed(self.receive(*terminal[:2]))
        screen.feed(self.send(terminal, b'10'))
        self.assertEqual(screen.prompt(), '请选择：10')
        screen.feed(self.send(terminal, b'\x7f'))
        self.assertEqual(screen.prompt(), '请选择：1')
        self.finish(terminal, b'\x04')

    def test_number_after_arrow_starts_a_new_choice(self):
        terminal = self.terminal()
        self.receive(*terminal[:2])
        self.send(terminal, b'\x1b[A')
        output = self.send(terminal, b'8')
        self.assertRegex(ANSI.sub('', output), r'>\s+8\. 查看全部功能状态')
        output = self.send(terminal, b'\n')
        self.assertIn('CALL:status', output)
        self.assertNotIn('CALL:install', output)
        self.finish(terminal)

    def test_unsupported_csi_sequences_do_not_become_numeric_input(self):
        for sequence in (b'\x1b[1;5A', b'\x1b[3~', b'\x1b[5~'):
            with self.subTest(sequence=sequence):
                terminal = self.terminal()
                screen = MenuScreen()
                screen.feed(self.receive(*terminal[:2]))
                output = self.send(terminal, sequence)
                screen.feed(output)
                self.assertEqual(screen.prompt(), '请选择：')
                self.assertNotIn('CALL:', output)
                self.finish(terminal, b'\n')

    def test_long_input_fits_prompt_without_wrapping_or_selecting_a_partial_number(self):
        script = SCRIPT.replace('"$ENTRY"', r'''
menu_snapshot() { MENU_TCP=bbr; MENU_STATES=(x x x x x); MENU_INPUT=$TEST_INPUT; }
"$ENTRY"
''')
        terminal = self.terminal(columns=80, script=script, TEST_INPUT='9' * 100)
        output = self.receive(*terminal[:2])
        prompt = ANSI.sub('', output).splitlines()[-1]
        self.assertLessEqual(len(prompt.replace('请选择：', ' ' * 8)), 78)
        self.assertNotIn('CALL:', output)
        output = self.send(terminal, b'\n')
        self.assertIn('无效选项', output)
        self.assertNotIn('CALL:', output)
        self.finish(terminal, b'\x04')

    def test_control_d_exits_and_restores_terminal_input(self):
        terminal = self.terminal()
        output = self.receive(*terminal[:2])
        self.assertNotIn('CALL:', output)
        self.finish(terminal, b'\x04')

    def test_escape_exits_both_menus_and_restores_terminal_input(self):
        for entry in ('main_menu', 'bbr_menu'):
            with self.subTest(entry=entry):
                terminal = self.terminal(ENTRY=entry)
                output = self.receive(*terminal[:2])
                self.assertNotIn('CALL:', output)
                self.finish(terminal, b'\x1b')

    def test_normal_exit_preserves_existing_signal_handlers(self):
        script = SCRIPT.replace('"$ENTRY"', r'''
trap 'printf existing-int' INT
trap 'printf existing-term' TERM
saved_int=$(trap -p INT); saved_term=$(trap -p TERM)
"$ENTRY"
[[ $(trap -p INT) == "$saved_int" && $(trap -p TERM) == "$saved_term" ]] || exit 99
printf 'HANDLERS_RESTORED\n'
''')
        terminal = self.terminal(script=script)
        self.receive(*terminal[:2])
        output = self.send(terminal, b'0\n', marker='HANDLERS_RESTORED')
        terminal[0].wait(timeout=4)
        self.assertEqual(terminal[0].returncode, 0, output)
        self.assertNotIn('CALL:', output)

    def test_interrupts_restore_terminal_input_in_a_controlling_session(self):
        # Keep the PTY session alive after Bash exits so we measure the actual
        # post-exit modes, rather than the modes seen inside Bash's EXIT trap.
        probe = '''import os,signal,subprocess,termios
signal.signal(signal.SIGINT, lambda *_: None)
before=termios.tcgetattr(0)
process=subprocess.Popen(['bash','-c',%r])
with open(os.environ['HOME']+'/menu-pid','w') as stream: stream.write(str(process.pid))
rc=process.wait()
after=termios.tcgetattr(0)
# BSD sets transient PENDIN when restoring canonical input with queued data.
before[3] &= ~getattr(termios, 'PENDIN', 0)
after[3] &= ~getattr(termios, 'PENDIN', 0)
print('PROBE:%%s:%%s' %% (rc, int(before == after)), flush=True)
''' % SCRIPT
        for interrupt in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(interrupt=interrupt):
                terminal = self.terminal(script=probe, controlling_session=True)
                self.receive(*terminal[:2])
                if interrupt == signal.SIGINT:
                    output = self.send(terminal, b'\x03', marker='PROBE:')
                else:
                    os.kill(int((self.home / 'menu-pid').read_text()), interrupt)
                    output = self.receive(*terminal[:2], marker='PROBE:')
                terminal[0].wait(timeout=4)
                self.assertIn(f'PROBE:{128 + interrupt}:1', output)
                self.assertNotIn('CALL:', output)

    def test_no_color_and_dumb_terminal_fall_back_to_plain_input(self):
        for env in ({'NO_COLOR': '1'}, {'TERM': 'dumb'}):
            with self.subTest(env=env):
                terminal = self.terminal(**env)
                output = self.receive(*terminal[:2])
                self.assertNotIn('\x1b', output)
                self.assertNotIn('↑', output)
                self.finish(terminal)

    def test_terminal_without_truecolor_uses_compatible_palette(self):
        for term, selected_background in (('xterm-256color', '\x1b[48;5;238m'),
                                           ('screen', '\x1b[100m')):
            with self.subTest(term=term):
                terminal = self.terminal(TERM=term, COLORTERM='')
                output = self.receive(*terminal[:2])
                self.assertNotIn('\x1b[38;2;', output)
                self.assertIn(selected_background, output)
                self.finish(terminal)

    def test_small_terminal_keeps_readable_numeric_menu_without_cursor_redraw(self):
        terminal = self.terminal(rows=16, columns=48)
        output = self.receive(*terminal[:2])
        plain = ANSI.sub('', output)
        self.assertIn('BBR 网络管理', plain)
        self.assertNotIn('↑', plain)
        self.assertNotRegex(output, r'\x1b\[\d+A')
        self.finish(terminal)

    def test_menu_rows_fit_terminal_cells_in_utf8_and_c_locales(self):
        for locale in ('C.UTF-8', 'C'):
            for entry in ('main_menu', 'bbr_menu'):
                with self.subTest(locale=locale, entry=entry):
                    terminal = self.terminal(columns=80, LC_ALL=locale, ENTRY=entry)
                    output = ANSI.sub('', self.receive(*terminal[:2]))
                    self.assertNotIn('\ufffd', output)
                    for line in output.replace('\r', '').splitlines():
                        width = sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F')
                                    else 1 for ch in line)
                        self.assertLessEqual(width, 78, repr(line))
                        if line and not line.startswith('请选择'):
                            self.assertEqual(width, 78, repr(line))
                    self.finish(terminal)

    def test_author_credit_is_in_both_headers_and_survives_minimum_window_redraw(self):
        for entry in ('main_menu', 'bbr_menu'):
            with self.subTest(entry=entry):
                terminal = self.terminal(rows=24, columns=64, ENTRY=entry)
                screen = MenuScreen(columns=64, rows=24)
                output = self.receive(*terminal[:2])
                plain = ANSI.sub('', output)
                section = '一键配置' if entry == 'main_menu' else '状态与启用'
                self.assertIn('tangbaichuan', plain)
                self.assertIn('https://github.com/reedtang666', plain)
                self.assertLess(plain.index('tangbaichuan'), plain.index(section))
                screen.feed(output)
                screen.feed(self.send(terminal, b'2'))
                visible = '\n'.join(''.join(row) for row in screen.cells)
                self.assertIn('tangbaichuan', visible)
                self.assertIn('https://github.com/reedtang666', visible)
                self.assertIn('ShellReady', visible)
                self.finish(terminal, b'\x04')

    def test_author_credit_keeps_full_url_in_narrow_and_plain_menus(self):
        for entry in ('main_menu', 'bbr_menu'):
            with self.subTest(entry=entry):
                result = self.pipe(ENTRY=entry)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('作者：tangbaichuan', result.stdout)
                self.assertIn('GitHub：https://github.com/reedtang666', result.stdout)
                self.assertNotIn('\x1b', result.stdout)
                terminal = self.terminal(rows=16, columns=48, ENTRY=entry)
                output = ANSI.sub('', self.receive(*terminal[:2]))
                self.assertIn('作者：tangbaichuan', output)
                self.assertIn('GitHub：https://github.com/reedtang666', output)
                self.finish(terminal)

    def test_resize_to_small_terminal_retains_the_visible_numeric_choice(self):
        terminal = self.terminal()
        self.receive(*terminal[:2])
        fcntl.ioctl(terminal[2], termios.TIOCSWINSZ, struct.pack('HHHH', 16, 48, 0, 0))
        output = self.send(terminal, b'2')
        self.assertNotIn('↑', ANSI.sub('', output))
        output = self.send(terminal, b'\n')
        self.assertIn('ShellReady / BBR 网络管理', ANSI.sub('', output))
        self.assertNotIn('CALL:', output)
        self.finish(terminal, b'0\n0\n')

    def test_resize_to_small_terminal_still_allows_editing_the_pending_number(self):
        terminal = self.terminal()
        self.receive(*terminal[:2])
        fcntl.ioctl(terminal[2], termios.TIOCSWINSZ, struct.pack('HHHH', 16, 48, 0, 0))
        self.send(terminal, b'2')
        # Delete the visible 2, then choose 8: this must not become option 28.
        output = self.send(terminal, b'\x7f8\n')
        self.assertIn('CALL:status', output)
        self.assertNotIn('CALL:install', output)
        self.finish(terminal)

    def test_component_badges_distinguish_disabled_broken_and_missing_without_running_tools(self):
        prefix = self.home / 'prefix'
        (prefix / 'bin').mkdir(parents=True)
        for tool in ('starship', 'atuin'):
            digest = 'a' * 64
            directory = prefix / 'tools' / f'{tool}-1-{digest[:12]}'
            directory.mkdir(parents=True)
            (directory / '.complete').write_text(digest)
            executable = directory / tool
            executable.write_text('#!/bin/sh\necho unexpected-tool-execution >&2\nexit 99\n')
            executable.chmod(0o755)
        (prefix / 'config/disabled').mkdir(parents=True)
        (prefix / 'config/disabled/atuin').touch()
        result = self.pipe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'Starship[^\n]*\[待修复\]')
        self.assertRegex(result.stdout, r'Atuin[^\n]*\[已停用\]')
        self.assertRegex(result.stdout, r'zoxide[^\n]*\[未安装\]')
        self.assertNotIn('unexpected-tool-execution', result.stderr)

    def test_badge_checks_the_active_entry_even_if_an_older_copy_is_complete(self):
        prefix = self.home / 'prefix'
        (prefix / 'bin').mkdir(parents=True)
        for version in ('1', '2'):
            directory = prefix / 'tools' / f'atuin-{version}-aaaaaaaaaaaa'
            directory.mkdir(parents=True)
            (directory / '.complete').write_text('a' * 64)
            binary = directory / 'atuin'
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o755 if version == '1' else 0o644)
        (prefix / 'bin/atuin').symlink_to(binary)
        result = self.pipe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'Atuin[^\n]*\[待修复\]')


if __name__ == '__main__':
    unittest.main()
