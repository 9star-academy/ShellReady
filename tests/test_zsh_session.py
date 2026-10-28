"""Real terminal journeys; OS accounts/packages are isolated by existing fixtures."""
import errno
import os
import pty
import select
import subprocess
import tarfile
import time
import unittest

import test_entry_transitions as transitions


class ZshSessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = transitions.EntryTransitionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.work = self.fixture.work
        self.repo = self.fixture.repo
        self.home = self.fixture.home
        entry = self.repo / 'install.sh'
        entry.write_text(entry.read_text().replace(
            '/tmp/shellready.XXXXXXXX', str(self.work / 'install.XXXXXXXX')))
        # Login account lookup and uid switching stay local; the actual Zsh and
        # its project startup configuration run unchanged in a PTY.
        with (self.repo / 'lib/common.sh').open('a') as common:
            common.write(r'''
getent() { printf '%s:x:123:123::%s:/bin/zsh\n' "$TARGET_USER" "$TARGET_HOME"; }
as_user() {
    if [[ "$1" == env && "${2:-}" == SHELL=* && "${3:-}" == /bin/zsh && "${4:-}" == -il ]]; then
        if (: >&9) 2>/dev/null; then echo lock-inherited >&2; return 99; fi
        printf '%s\n' "$TARGET_USER:$*" >> "$TEST_WORK/session-calls"
    fi
    env HOME="$TARGET_HOME" USER="$TARGET_USER" LOGNAME="$TARGET_USER" "$@"
}
''')
        self.home.joinpath('.zshrc').write_text(
            'print -r -- "SESSION_READY:$USER:$SHELL"\n')

    def terminal(self, *args, choices='', session=True, manager=False, bootstrap=False,
                 session_exit=0, command=None):
        if command is None:
            command = [str(self.fixture.prefix / 'bin/shellready')] if manager else [
                'bash', str(self.repo / 'install.sh')]
        if bootstrap:
            command = ['bash', str(transitions.ROOT / 'bootstrap.sh')]
        master, slave = pty.openpty()
        process = subprocess.Popen([*command, *args], stdin=slave, stdout=slave,
                                   stderr=slave, env={**self.fixture.env, 'TERM': 'dumb'})
        output = bytearray()
        sent_exit = False
        try:
            if choices:
                os.write(master, choices.encode())
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                if b'SESSION_READY:' in output and not sent_exit:
                    self.assertTrue(session, output.decode(errors='replace'))
                    self.assertEqual(list(self.work.glob('install.*')), [],
                                     'installation scratch files survived into the session')
                    os.write(master, ('print -r -- "ACTIVE:$USER:$SHELL:${_SHELLREADY_LOADED:-0}"\n'
                                      f'exit {session_exit}\n').encode())
                    sent_exit = True
                if process.poll() is not None:
                    break
            process.wait(timeout=2)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            os.close(master)
            os.close(slave)
        text = output.decode(errors='replace')
        self.assertEqual(sent_exit, session, text)
        return process.returncode, text

    def seed_all(self):
        self.fixture.seed('trzsz', 'starship', 'suggestions', 'atuin', 'zoxide')

    def test_install_enters_target_zsh_after_cleanup_with_plain_prompts(self):
        self.seed_all()
        rc, output = self.terminal('--skip-bbr', '--user', 'fixture-user')
        self.assertEqual(rc, 0, output)
        self.assertIn('无需重新连接 SSH', output)
        self.assertIn('输入 exit', output)
        self.assertIn('ACTIVE:fixture-user:/bin/zsh:1', output)
        self.assertIn('已返回原来的终端', output)
        self.assertNotIn('lock-inherited', output)
        calls = (self.work / 'session-calls').read_text().splitlines()
        self.assertEqual(calls, ['fixture-user:env SHELL=/bin/zsh /bin/zsh -il'])

    def test_noninteractive_install_finishes_without_opening_a_session(self):
        self.seed_all()
        result = self.fixture.run_cli('--skip-bbr')
        self.assertNotIn('SESSION_READY:', result.stdout)
        self.assertFalse((self.work / 'session-calls').exists())

    def test_keep_shell_does_not_enter_zsh_even_in_terminal(self):
        self.seed_all()
        rc, output = self.terminal('--skip-bbr', '--keep-shell', session=False)
        self.assertEqual(rc, 0, output)
        self.assertFalse((self.work / 'session-calls').exists())

    def launcher_script(self, before=''):
        script = self.work / 'launch.sh'
        script.write_text('''#!/bin/bash
set -euo pipefail
ROOT="$TEST_WORK/repo"
source "$ROOT/lib/common.sh"
source "$ROOT/modules/shell.sh"
TARGET_USER=fixture-user; KEEP_SHELL=0
resolve_user
mkdir -p "$PREFIX/config"
cp "$ROOT/config/init.zsh" "$PREFIX/config/init.zsh"
shell_block > "$TARGET_HOME/.zshrc"
''' + before + '\nstart_zsh_session\n')
        return ['bash', str(script)]

    def test_missing_config_or_unverified_account_does_not_open_zsh(self):
        for before, expected in (
                ('rm "$PREFIX/config/init.zsh"', '配置尚未就绪'),
                ('getent() { echo "fixture:x:123:123::/tmp:/bin/bash"; }', '登录 Shell 尚未确认为 Zsh'),
                ('getent() { return 1; }', '登录 Shell 尚未确认为 Zsh')):
            with self.subTest(before=before):
                rc, output = self.terminal(command=self.launcher_script(before), session=False)
                self.assertEqual(rc, 0, output)
                self.assertIn(expected, output)
                self.assertFalse((self.work / 'session-calls').exists())

    def test_redirected_output_does_not_open_zsh_even_with_terminal_input(self):
        command = self.launcher_script()
        master, slave = pty.openpty()
        try:
            result = subprocess.run(command, stdin=slave, capture_output=True,
                                    text=True, timeout=5, env=self.fixture.env)
        finally:
            os.close(master)
            os.close(slave)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('未自动进入 Zsh', result.stdout)
        self.assertFalse((self.work / 'session-calls').exists())

    def test_failed_install_does_not_enter_zsh(self):
        self.seed_all()
        with (self.repo / 'modules/tools.sh').open('a') as tools:
            tools.write('\ninstall_trzsz() { return 1; }\n')
        rc, output = self.terminal('--skip-bbr', session=False)
        self.assertEqual(rc, 1, output)
        self.assertFalse((self.work / 'session-calls').exists())

    def test_later_failed_menu_install_cancels_earlier_pending_session(self):
        self.seed_all()
        with (self.repo / 'modules/tools.sh').open('a') as tools:
            tools.write(r'''
install_trzsz() {
    [[ ! -e "$TEST_WORK/first-install" ]] || return 1
    touch "$TEST_WORK/first-install"
    install_tool trzsz
}
''')
        rc, output = self.terminal('menu', '--skip-bbr', choices='1\n1\n0\n', session=False)
        self.assertEqual(rc, 0, output)
        self.assertIn('操作失败', output)
        self.assertFalse((self.work / 'session-calls').exists())

    def test_session_exit_status_does_not_reclassify_a_successful_install(self):
        self.seed_all()
        rc, output = self.terminal('--skip-bbr', session_exit=7)
        self.assertEqual(rc, 0, output)
        self.assertIn('退出码 7', output)
        self.assertIn('安装结果不变', output)

    def test_sudo_path_uses_existing_target_user_switch_before_starting_zsh(self):
        self.seed_all()
        common_path = self.repo / 'lib/common.sh'
        original = (transitions.ROOT / 'lib/common.sh').read_text()
        as_user = original.split('as_user() {', 1)[1].split('\n}', 1)[0]
        with common_path.open('a') as common:
            common.write('\nas_user() {' + as_user + '\n}\n')
            common.write(r'''
id() { case "$*" in '-un') echo operator;; '-u') echo 0;; '-u fixture-user') echo 123;; *) return 99;; esac; }
runuser() {
    printf '%s\n' "$*" >> "$TEST_WORK/runuser-calls"
    [[ "$1" == -u && "$2" == fixture-user && "$3" == -- ]] || return 99
    shift 3
    "$@"
}
''')
        rc, output = self.terminal('--skip-bbr', '--user', 'fixture-user')
        self.assertEqual(rc, 0, output)
        self.assertIn('ACTIVE:fixture-user:/bin/zsh:1', output)
        calls = (self.work / 'runuser-calls').read_text().splitlines()
        self.assertTrue(any(line.startswith('-u fixture-user -- env ') and
                            line.endswith('env SHELL=/bin/zsh /bin/zsh -il') for line in calls), calls)

    def test_skipped_bbr_keeps_partial_exit_without_entering_zsh(self):
        self.seed_all()
        with (self.repo / 'modules/bbr.sh').open('a') as bbr:
            bbr.write('\ninstall_bbr() { return 2; }\n')
        rc, output = self.terminal(session=False)
        self.assertEqual(rc, 2, output)

    def test_menu_waits_until_exit_before_entering_zsh(self):
        self.seed_all()
        rc, output = self.terminal('menu', '--skip-bbr', choices='1\n0\n')
        self.assertEqual(rc, 0, output)
        self.assertIn('退出总菜单后会自动进入 Zsh', output)
        self.assertEqual((self.work / 'session-calls').read_text().count('\n'), 1)
        self.assertLess(output.index('退出总菜单后会自动进入 Zsh'), output.index('SESSION_READY:'))

    def test_component_install_from_menu_also_enters_zsh_on_exit(self):
        self.fixture.seed('atuin')
        rc, output = self.terminal('menu', '--skip-bbr', choices='6\n1\n0\n0\n')
        self.assertEqual(rc, 0, output)
        self.assertTrue((self.fixture.prefix / 'bin/atuin').exists())

    def test_browsing_menu_does_not_start_a_shell(self):
        rc, output = self.terminal('menu', choices='0\n', session=False)
        self.assertEqual(rc, 0, output)

    def test_uninstall_cancels_pending_session(self):
        self.seed_all()
        rc, output = self.terminal('menu', '--skip-bbr', choices='1\n10\ny\n', session=False)
        self.assertEqual(rc, 0, output)
        self.assertFalse((self.work / 'session-calls').exists())

    def test_self_update_does_not_open_a_pending_session(self):
        self.seed_all()
        with (self.repo / 'modules/update.sh').open('a') as update:
            update.write('\nself_update() { return 0; }\n')
        rc, output = self.terminal('menu', '--skip-bbr', choices='1\n11\ny\n', session=False)
        self.assertEqual(rc, 0, output)

    def test_remote_bootstrap_enters_zsh_and_cleans_up_after_exit(self):
        self.seed_all()
        with tarfile.open(self.work / 'source.tar.gz', 'w:gz') as archive:
            archive.add(self.repo, arcname='snapshot')
        (self.work / 'commit.json').write_text('{\n  "sha": "' + 'a' * 40 + '",\n}\n')
        curl = self.work / 'bin/curl'
        curl.write_text('''#!/bin/bash
url=''; dest=''
while (($#)); do
    case "$1" in https://*) url=$1; shift;; -o) dest=$2; shift 2;; *) shift;; esac
done
case "$url" in
    https://api.github.com/*) cp "$TEST_WORK/commit.json" "$dest";;
    https://codeload.github.com/*) cp "$TEST_WORK/source.tar.gz" "$dest";;
    *) exit 99;;
esac
''')
        curl.chmod(0o755)
        bootstrap_tmp = self.work / 'bootstrap-tmp'
        bootstrap_tmp.mkdir()
        self.fixture.env['TMPDIR'] = str(bootstrap_tmp)
        rc, output = self.terminal('--skip-bbr', bootstrap=True)
        self.assertEqual(rc, 0, output)
        self.assertIn('ShellReady snapshot:', output)
        self.assertEqual(list(bootstrap_tmp.iterdir()), [])

    def test_update_repair_and_installed_manager_share_the_session_flow(self):
        self.seed_all()
        self.fixture.run_cli('--skip-bbr')
        for action in ('update', 'repair'):
            with self.subTest(action=action):
                rc, output = self.terminal(action, '--skip-bbr')
                self.assertEqual(rc, 0, output)
        rc, output = self.terminal(choices='1\n0\n', manager=True)
        self.assertEqual(rc, 0, output)
