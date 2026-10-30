"""Menu journeys run without touching host packages, users or networking."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MenuTests(unittest.TestCase):
    def menu(self, choices, entry='main_menu', fail=False, rc=None):
        with tempfile.TemporaryDirectory() as tmp:
            script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/components.sh"
source "$ROOT/modules/menu.sh"
TARGET_USER=fixture; KEEP_SHELL=1; SKIP_BBR=1
PREFIX="$HOME/prefix"
menu_action() { printf 'CALL:%s\n' "$*"; return "$TEST_RC"; }
component_status() { echo 'fixture 已安装'; }
main_entry=$ENTRY
"$main_entry"
'''
            return subprocess.run(['bash', '-c', script], input=choices, text=True,
                                  capture_output=True, timeout=5,
                                  env={**os.environ, 'ROOT': str(ROOT), 'ENTRY': entry,
                                       'TEST_RC': str(rc) if rc is not None else ('1' if fail else '0'), 'HOME': tmp})

    def test_main_exit_does_not_dispatch_install(self):
        result = self.menu('0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ShellReady 管理菜单', result.stdout)
        self.assertNotIn('CALL:', result.stdout)

    def test_eof_exits_and_invalid_input_reprompts(self):
        result = self.menu('bad\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('无效', result.stdout)
        self.assertNotIn('CALL:', result.stdout)

    def test_all_install_is_explicit_and_failure_returns_to_menu(self):
        result = self.menu('1\n8\n0\n', fail=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CALL:install', result.stdout)
        self.assertIn('CALL:status', result.stdout)
        self.assertIn('失败', result.stdout)

    def test_component_menu_only_dispatches_selected_tool(self):
        result = self.menu('6\n1\n3\n2\n0\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        for operation in ('install', 'disable', 'enable'):
            self.assertIn(f'CALL:component atuin {operation}', result.stdout)
        self.assertNotIn('CALL:install\n', result.stdout)

    def test_cancel_uninstall_and_fq_do_not_dispatch(self):
        result = self.menu('10\nn\n2\n3\nn\n0\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('CALL:', result.stdout)

    def test_bbr_submenu_and_restore(self):
        result = self.menu('1\n2\n5\ny\n0\n', entry='bbr_menu')
        self.assertEqual(result.returncode, 0, result.stderr)
        for action in ('bbr-status', 'bbr-enable', 'bbr-restore'):
            self.assertIn(f'CALL:{action}', result.stdout)

    def test_self_update_cancel_or_eof_does_not_download(self):
        for choices in ('11\nn\n0\n', '11\n'):
            with self.subTest(choices=choices):
                result = self.menu(choices)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('更新 ShellReady', result.stdout)
                self.assertNotIn('CALL:', result.stdout)

    def test_self_update_success_or_partial_exits_old_menu(self):
        for code in (0, 2):
            with self.subTest(code=code):
                result = self.menu('11\ny\n8\n0\n', rc=code)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('CALL:self-update', result.stdout)
                self.assertNotIn('CALL:status', result.stdout)
                self.assertIn('shellready', result.stdout)
                if code == 2:
                    self.assertIn('待验证', result.stdout)

    def test_failed_self_update_returns_to_menu(self):
        result = self.menu('11\ny\n8\n0\n', fail=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CALL:self-update', result.stdout)
        self.assertIn('CALL:status', result.stdout)
        self.assertIn('失败', result.stdout)

    def test_manager_defaults_to_menu_but_explicit_install_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/tools.sh"
TARGET_HOME="$TEST_HOME"; TARGET_USER=$(id -un)
PREFIX="$TARGET_HOME/prefix"; WORK="$TARGET_HOME/work"
mkdir -p "$PREFIX/bin" "$WORK"
as_user() { "$@"; }
install_manager
[[ -s "$PREFIX/app/bootstrap.sh" && -s "$PREFIX/app/modules/update.sh" ]] || exit 99
printf '#!/bin/bash\nprintf "ACTION:%%s\\n" "$*"\n' > "$PREFIX/app/install.sh"
"$PREFIX/bin/shellready"
"$PREFIX/bin/shellready" install
'''
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                    env={**os.environ, 'ROOT': str(ROOT), 'TEST_HOME': tmp})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['ACTION:menu', 'ACTION:install'])

    def test_real_menu_exit_needs_no_privilege_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            shutil.copy(ROOT / 'install.sh', repo)
            shutil.copy(ROOT / 'bootstrap.sh', repo)
            for name in ('lib', 'modules'):
                shutil.copytree(ROOT / name, repo / name)
            with (repo / 'lib/common.sh').open('a') as f:
                f.write('''\ncheck_platform() { ARCH=x86_64; }
resolve_user() { TARGET_HOME="$TEST_HOME"; PREFIX="$TARGET_HOME/prefix"; STATE="$TARGET_HOME/state"; }
''')
            result = subprocess.run(['bash', str(repo / 'install.sh'), 'menu'], input='0\n',
                                    capture_output=True, text=True, timeout=5,
                                    env={**os.environ, 'TEST_HOME': tmp})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('ShellReady 管理菜单', result.stdout)
            self.assertFalse((Path(tmp) / 'prefix').exists())
            self.assertFalse((Path(tmp) / 'state').exists())

    def test_kernel_selection_and_cancel(self):
        script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/menu.sh"
kernel_release_tags() { printf '%s\n' x86_64-7.2.0 x86_64-7.1.0; }
menu_action() { printf 'CALL:%s\n' "$*"; }
menu_kernel_install
'''
        for choices, expected in [('2\ny\n', 'CALL:bbrv3 --tag x86_64-7.1.0 --yes'),
                                  ('1\nn\n', None), ('99\n', None), ('0\n', None)]:
            with self.subTest(choices=choices):
                result = subprocess.run(['bash', '-c', script], input=choices, text=True,
                                        capture_output=True, env={**os.environ, 'ROOT': str(ROOT)})
                self.assertEqual(result.returncode, 0, result.stderr)
                if expected:
                    self.assertIn(expected, result.stdout)
                else:
                    self.assertNotIn('CALL:', result.stdout)

    def test_subprocess_keeps_target_and_flags_without_consuming_menu_input(self):
        script = r'''set -euo pipefail
source "$ROOT/modules/menu.sh"
TARGET_USER=fixture; KEEP_SHELL=1; SKIP_BBR=1
bash() { printf '%s\n' "$*"; if IFS= read -r stolen; then exit 99; fi; }
menu_action component atuin install
IFS= read -r remaining
[[ "$remaining" == next ]] || exit 99
'''
        result = subprocess.run(['bash', '-c', script], input='next\n', text=True,
                                capture_output=True, env={**os.environ, 'ROOT': str(ROOT)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('component atuin install --user fixture --keep-shell --skip-bbr', result.stdout)

    def test_new_mutations_require_confirmation_before_platform_checks(self):
        for args in (['bbr-fq'], ['bbr-restore'], ['component', '../other', 'remove'],
                     ['component', 'atuin', 'invalid']):
            with self.subTest(args=args):
                result = subprocess.run(['bash', str(ROOT / 'install.sh'), *args],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn('目标必须是 Linux', result.stderr)
