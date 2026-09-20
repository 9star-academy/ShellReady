"""Isolated behavioral tests. No system packages, kernel or real HOME are modified."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ShellReadyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def bash(self, body):
        prelude = '''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/shell.sh"
source "$ROOT/modules/bbr.sh"
source "$ROOT/modules/tools.sh"
source "$ROOT/modules/kernel.sh"
TARGET_HOME="$TEST_HOME"
TARGET_USER="$(id -un)"
PREFIX="$TARGET_HOME/.local/share/shellready"
STATE="$TARGET_HOME/.local/state/shellready"
WORK="$TARGET_HOME/work"
BBR_SYSCTL_DIRS=("$WORK/sysctl.d")
BBR_SYSCTL_MAIN="$WORK/sysctl.conf"
mkdir -p "$PREFIX" "$STATE" "$WORK"
as_user() { env HOME="$TARGET_HOME" "$@"; }
'''
        return subprocess.run(['bash', '-c', prelude + body], env={**os.environ, 'ROOT': str(ROOT), 'TEST_HOME': str(self.home)}, text=True, errors="replace", capture_output=True)

    def success(self, body):
        p = self.bash(body)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def test_help_without_privilege_or_linux(self):
        p = subprocess.run(['bash', str(ROOT/'install.sh'), '--help'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('bbrv3', p.stdout)

    def test_unknown_option_fails(self):
        p = subprocess.run(['bash', str(ROOT/'install.sh'), '--invalid'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('未知参数', p.stderr)

    def test_config_install_is_idempotent_and_preserves_existing(self):
        self.success('''printf 'alias mine="echo mine"\n' > "$TARGET_HOME/.zshrc"
add_shell_block "$TARGET_HOME/.zshrc"
add_shell_block "$TARGET_HOME/.zshrc"
''')
        data = (self.home/'.zshrc').read_text()
        self.assertEqual(data.count('# >>> ShellReady >>>'), 1)
        self.assertIn('alias mine="echo mine"', data)

    def test_uninstall_preserves_edits_outside_block(self):
        self.success('''printf '# original\n' > "$TARGET_HOME/.zshrc"
add_shell_block "$TARGET_HOME/.zshrc"
printf '# added later\n' >> "$TARGET_HOME/.zshrc"
remove_shell_block "$TARGET_HOME/.zshrc"
''')
        data = (self.home/'.zshrc').read_text()
        self.assertIn('# original', data)
        self.assertIn('# added later', data)
        self.assertNotIn('ShellReady', data)

    def test_symlink_config_is_not_replaced(self):
        self.success('''printf '# original\n' > "$TARGET_HOME/dotfile"
ln -s "$TARGET_HOME/dotfile" "$TARGET_HOME/.zshrc"
if add_shell_block "$TARGET_HOME/.zshrc"; then exit 99; fi
''')
        self.assertTrue((self.home/'.zshrc').is_symlink())
        self.assertEqual((self.home/'dotfile').read_text(), '# original\n')

    def test_malformed_block_is_not_modified(self):
        self.success('''printf '# >>> ShellReady >>>\nuser content\n' > "$TARGET_HOME/.zshrc"
cp "$TARGET_HOME/.zshrc" "$WORK/before"
if add_shell_block "$TARGET_HOME/.zshrc"; then exit 99; fi
cmp "$TARGET_HOME/.zshrc" "$WORK/before"
''')

    def test_config_missing_newline_does_not_consume_user_content(self):
        self.success('''printf '# no newline' > "$TARGET_HOME/.zshrc"
add_shell_block "$TARGET_HOME/.zshrc"
remove_shell_block "$TARGET_HOME/.zshrc"
''')
        self.assertIn('# no newline', (self.home/'.zshrc').read_text())

    def test_checksum_failure_is_reported(self):
        self.success('''printf broken > "$WORK/archive"
if verify_sha256 "$WORK/archive" aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; then exit 99; fi
''')

    def test_checksum_success(self):
        self.success('''printf abc > "$WORK/archive"
verify_sha256 "$WORK/archive" ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
''')

    def test_bbr_unsupported_skips_without_system_write(self):
        self.success('''SYSCTL_FILE="$WORK/bbr.conf"
BBR_STATE="$WORK/bbr-state"
sysctl() { case "$*" in '-n net.ipv4.tcp_available_congestion_control') echo 'reno cubic';; *) return 1;; esac; }
modprobe() { return 1; }
rc=0
install_bbr || rc=$?
[[ "$rc" == 2 ]] || exit 1
[[ ! -e "$SYSCTL_FILE" ]] || exit 1
''')

    def test_manifest_has_unique_verified_assets(self):
        rows = [x.split('\t') for x in (ROOT/'config/assets.tsv').read_text().splitlines() if x and not x.startswith('#')]
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({(x[0], x[2]) for x in rows}), 9)
        for row in rows:
            self.assertEqual(len(row), 5)
            self.assertRegex(row[4], r'^[0-9a-f]{64}$')
            self.assertTrue(row[3].startswith('https://'))
            self.assertNotIn('/latest/', row[3])

    def test_failed_step_stops_and_next_step_runs(self):
        self.success('''RESULTS=(); FAILED=0; SKIPPED=0
broken() { false; touch "$WORK/should-not-exist"; }
good() { touch "$WORK/next"; }
run_step broken broken
run_step good good
[[ "$FAILED" == 1 && -e "$WORK/next" && ! -e "$WORK/should-not-exist" ]] || exit 1
''')

    def test_modified_block_is_refused_on_duplicate_markers(self):
        self.success('''printf '# >>> ShellReady >>>\n# <<< ShellReady <<<\n# >>> ShellReady >>>\n# <<< ShellReady <<<\n' > "$TARGET_HOME/.zshrc"
if add_shell_block "$TARGET_HOME/.zshrc"; then exit 99; fi
''')

    def test_existing_unowned_prefix_is_preserved(self):
        self.success('''printf keep > "$PREFIX/user-data"
if prepare_user_dirs; then exit 99; fi
[[ $(cat "$PREFIX/user-data") == keep ]] || exit 1
''')

    def test_atomic_write_retains_destination_on_read_failure(self):
        self.success('''printf original > "$PREFIX/file"
if user_write "$PREFIX/file" "$WORK/missing"; then exit 99; fi
[[ $(cat "$PREFIX/file") == original ]] || exit 1
''')

    def test_download_failure_does_not_replace_valid_file(self):
        self.success('''printf original > "$WORK/file"
curl() { return 22; }
if download https://example.com/file "$WORK/file"; then exit 99; fi
[[ $(cat "$WORK/file") == original ]] || exit 1
''')

    def test_download_rejects_plain_http(self):
        self.success('''if download http://example.com/file "$WORK/file"; then exit 99; fi
[[ ! -e "$WORK/file" ]] || exit 1
''')

    def test_bbr_install_repeat_and_restore(self):
        self.success('''SYSCTL_FILE="$WORK/bbr.conf"; BBR_STATE="$WORK/bbr-state"
printf cubic > "$WORK/algo"
sha256sum() { shasum -a 256 "$@"; }
sysctl() {
 case "$*" in
  '-n net.ipv4.tcp_available_congestion_control') echo 'reno cubic bbr';;
  '-n net.ipv4.tcp_congestion_control') cat "$WORK/algo";;
  '-w net.ipv4.tcp_congestion_control='*) printf '%s' "${2#*=}" > "$WORK/algo";;
  *) return 1;;
 esac
}
install_bbr
install_bbr
[[ $(cat "$BBR_STATE/original") == cubic ]] || exit 1
[[ $(cat "$WORK/algo") == bbr ]] || exit 1
restore_bbr
[[ $(cat "$WORK/algo") == cubic && ! -e "$SYSCTL_FILE" ]] || exit 1
''')

    def test_bbr_will_not_replace_foreign_config(self):
        self.success('''SYSCTL_FILE="$WORK/bbr.conf"; BBR_STATE="$WORK/state"
printf foreign > "$SYSCTL_FILE"
sysctl() { echo 'cubic bbr'; }
if install_bbr; then exit 99; fi
[[ $(cat "$SYSCTL_FILE") == foreign ]] || exit 1
''')

    def test_bbr_restore_preserves_later_config_edit(self):
        self.success('''SYSCTL_FILE="$WORK/bbr.conf"; BBR_STATE="$WORK/state"
mkdir -p "$BBR_STATE"
printf cubic > "$BBR_STATE/original"
printf aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa > "$BBR_STATE/config.sha256"
printf edited > "$SYSCTL_FILE"
if restore_bbr; then exit 99; fi
[[ $(cat "$SYSCTL_FILE") == edited && -e "$BBR_STATE/original" ]] || exit 1
''')

    def test_bbr_restore_preserves_later_runtime_change(self):
        self.success('''SYSCTL_FILE="$WORK/bbr.conf"; BBR_STATE="$WORK/state"
mkdir -p "$BBR_STATE"
printf cubic > "$BBR_STATE/original"
sysctl() { echo reno; }
if restore_bbr; then exit 99; fi
[[ -e "$BBR_STATE/original" ]] || exit 1
''')

    def test_bbr_module_load_is_rechecked(self):
        self.success('''SYSCTL_FILE="$WORK/bbr.conf"; BBR_STATE="$WORK/state"
sysctl() { echo 'reno cubic'; }
modprobe() { touch "$WORK/modprobe-called"; }
rc=0; install_bbr || rc=$?
[[ "$rc" == 2 && -e "$WORK/modprobe-called" && ! -e "$SYSCTL_FILE" ]] || exit 1
''')

    def test_kernel_rejects_max_and_wrong_arch(self):
        self.success('''ARCH=x86_64
for TAG in arm64-7.2.6 x86_64-7.2.6-max latest '../bad'; do
 if validate_kernel_tag; then exit 99; fi
done
TAG=x86_64-7.2.6
validate_kernel_tag
''')

    def test_cli_kernel_requires_explicit_confirmation(self):
        p = subprocess.run(['bash', str(ROOT/'install.sh'), 'bbrv3', '--tag', 'x86_64-7.2.6'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('--yes', p.stderr)

    def test_cli_rejects_missing_user_value(self):
        p = subprocess.run(['bash', str(ROOT/'install.sh'), '--user'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('缺少参数', p.stderr)

    def test_cli_rejects_conflicting_actions(self):
        p = subprocess.run(['bash', str(ROOT/'install.sh'), 'install', 'uninstall'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('只能指定一个操作', p.stderr)

    def test_no_interactive_hooks_in_noninteractive_zsh(self):
        import shutil
        if not shutil.which('zsh'):
            self.skipTest('zsh unavailable')
        p = subprocess.run(['zsh', '-f', '-c', 'source "$1"; print -r -- "${_SHELLREADY_LOADED:-not-loaded}"', 'zsh', str(ROOT/'config/init.zsh')], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), 'not-loaded')

    def test_tool_install_repeat_preserves_unmanaged_tool(self):
        self.success('''ARCH=x86_64
mkdir -p "$WORK/fixture" "$WORK/root/config" "$TARGET_HOME/.local/bin"
printf '#!/bin/sh\nprintf "zoxide fixture\\n"\n' > "$WORK/fixture/zoxide"
printf original > "$TARGET_HOME/.local/bin/zoxide"
tar -czf "$WORK/tool.tar.gz" -C "$WORK/fixture" zoxide
hash=$(shasum -a 256 "$WORK/tool.tar.gz" | awk '{print $1}')
printf 'zoxide\t1.0.0\tx86_64\thttps://example.com/tool\t%s\n' "$hash" > "$WORK/root/config/assets.tsv"
ROOT="$WORK/root"
download() { cp "$WORK/tool.tar.gz" "$2"; }
mkdir -p "$PREFIX/bin" "$PREFIX/tools"
install_zoxide
install_zoxide
rm "$(readlink "$PREFIX/bin/zoxide")"
install_zoxide
[[ -x "$PREFIX/bin/zoxide" && $(cat "$TARGET_HOME/.local/bin/zoxide") == original ]] || exit 1
[[ $(find "$PREFIX/tools" -name .complete | wc -l | tr -d ' ') == 1 ]] || exit 1
''')

    def test_bad_tool_download_does_not_activate(self):
        self.success('''ARCH=x86_64
mkdir -p "$WORK/root/config" "$PREFIX/bin"
printf 'zoxide\t1.0.0\tx86_64\thttps://example.com/tool\taaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$WORK/root/config/assets.tsv"
ROOT="$WORK/root"
download() { printf broken > "$2"; }
RESULTS=(); FAILED=0; SKIPPED=0
run_step zoxide install_zoxide
[[ "$FAILED" == 1 && ! -e "$PREFIX/bin/zoxide" ]] || exit 1
''')

    def test_interactive_zsh_initializes_once_and_keeps_cd(self):
        import shutil
        if not shutil.which('zsh'):
            self.skipTest('zsh unavailable')
        prefix = self.home/'.local/share/shellready'
        (prefix/'bin').mkdir(parents=True)
        for tool in ['atuin','starship','zoxide']:
            f=prefix/'bin'/tool
            f.write_text('#!/bin/sh\necho "typeset -g '+tool.upper()+'_READY=1"\necho called >> "$HOME/'+tool+'.calls"\n')
            f.chmod(0o755)
        p=subprocess.run(['zsh','-dfi','-c','source "$1"; source "$1"; print -r -- "$ATUIN_READY $STARSHIP_READY $ZOXIDE_READY"; whence -w cd', 'zsh',str(ROOT/'config/init.zsh')],env={**os.environ,'HOME':str(self.home),'ZDOTDIR':str(self.home)},capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('1 1 1',p.stdout)
        self.assertIn('cd: builtin',p.stdout)
        for tool in ['atuin','starship','zoxide']:
            self.assertEqual((self.home/(tool+'.calls')).read_text().splitlines(),['called'])

    def test_shell_install_keeps_custom_theme_and_imports_once(self):
        import shutil
        if not shutil.which('zsh'):
            self.skipTest('zsh unavailable')
        self.success('''KEEP_SHELL=1; LOGIN_SHELL=/bin/bash
mkdir -p "$PREFIX/bin" "$PREFIX/config/atuin"
printf 'custom = true\n' > "$PREFIX/config/starship.toml"
printf 'echo previous\n' > "$TARGET_HOME/.bash_history"
cat > "$PREFIX/bin/atuin" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$HOME/import.calls"
EOF
chmod +x "$PREFIX/bin/atuin"
install_shell
install_shell
[[ $(cat "$PREFIX/config/starship.toml") == 'custom = true' ]] || exit 1
[[ $(cat "$TARGET_HOME/import.calls") == 'import bash' ]] || exit 1
''')

    def test_bbr_failed_apply_restores_previous_state(self):
        self.success('''SYSCTL_FILE="$WORK/bbr.conf"; BBR_STATE="$WORK/bbr-state"
printf cubic > "$WORK/algo"
sha256sum() { shasum -a 256 "$@"; }
sysctl() {
 case "$*" in
  '-n net.ipv4.tcp_available_congestion_control') echo 'cubic bbr';;
  '-n net.ipv4.tcp_congestion_control') cat "$WORK/algo";;
  '-w net.ipv4.tcp_congestion_control=bbr') return 1;;
  '-w net.ipv4.tcp_congestion_control=cubic') printf cubic > "$WORK/algo";;
  *) return 1;;
 esac
}
RESULTS=(); FAILED=0; SKIPPED=0
run_step bbr install_bbr
[[ "$FAILED" == 1 && ! -e "$SYSCTL_FILE" && $(cat "$WORK/algo") == cubic ]] || exit 1
''')

    def test_kernel_pending_is_not_reported_as_running(self):
        self.success('''KERNEL_STATE="$WORK/kernels"
mkdir -p "$KERNEL_STATE/test"
printf '7.2.6-joeyblog-bbrv3' > "$KERNEL_STATE/test/kernel"
touch "$KERNEL_STATE/test/installed"
uname() { echo old-kernel; }
rc=0; status_kernel > "$WORK/status" || rc=$?
[[ "$rc" == 2 ]] || exit 1
grep -q '当前未运行' "$WORK/status"
''')

    def test_kernel_running_requires_loaded_v3_and_bbr(self):
        self.success('''KERNEL_STATE="$WORK/kernels"
mkdir -p "$KERNEL_STATE/test"
printf '7.2.6-joeyblog-bbrv3' > "$KERNEL_STATE/test/kernel"
touch "$KERNEL_STATE/test/installed"
uname() { echo 7.2.6-joeyblog-bbrv3; }
cat() { if [[ "$1" == /sys/module/tcp_bbr/version ]]; then echo 3; else command cat "$@"; fi; }
sysctl() { echo bbr; }
status_kernel > "$WORK/status"
grep -q '已加载 BBRv3' "$WORK/status"
sysctl() { echo cubic; }
rc=0; status_kernel || rc=$?
[[ "$rc" == 2 ]] || exit 1
''')

    def test_kernel_remove_refuses_running_kernel(self):
        self.success('''ARCH=x86_64; TAG=x86_64-7.2.6; KERNEL_STATE="$WORK/kernels"
mkdir -p "$KERNEL_STATE/$TAG"
printf linux-image-7.2.6-joeyblog-bbrv3 > "$KERNEL_STATE/$TAG/package"
printf 7.2.6-joeyblog-bbrv3 > "$KERNEL_STATE/$TAG/kernel"
uname() { echo 7.2.6-joeyblog-bbrv3; }
if remove_kernel; then exit 99; fi
[[ -e "$KERNEL_STATE/$TAG/package" ]] || exit 1
''')

    def test_local_manager_help_works_after_source_directory_changes(self):
        self.success('''mkdir -p "$PREFIX/bin"
install_manager
"$PREFIX/bin/shellready" --help > "$WORK/help"
grep -q kernel-remove "$WORK/help"
''')

if __name__ == '__main__':
    unittest.main()
