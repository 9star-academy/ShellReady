"""Shell startup/recovery regressions using a temporary HOME, never login changes."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ShellStartupRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def bash(self, body):
        env = {**os.environ, "ROOT": str(ROOT), "HOME": str(self.home)}
        env.pop("ZDOTDIR", None)
        prelude = '''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/shell.sh"
TARGET_HOME="$HOME"; TARGET_USER="$(id -un)"
PREFIX="$HOME/.local/share/shellready"; STATE="$HOME/.local/state/shellready"; WORK="$HOME/work"
LOGIN_SHELL=/bin/bash; KEEP_SHELL=1
as_user() { env HOME="$TARGET_HOME" "$@"; }
mkdir -p "$PREFIX/config/atuin" "$STATE" "$WORK"
'''
        return subprocess.run(["bash", "-c", prelude + body], env=env,
                              capture_output=True, text=True)

    def assert_success(self, body):
        result = self.bash(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    @unittest.skipUnless(shutil.which("zsh"), "zsh unavailable")
    def test_login_profile_zdotdir_is_refused_before_config_write(self):
        (self.home / ".zprofile").write_text('export ZDOTDIR="$HOME/custom-zsh"\n')
        (self.home / "custom-zsh").mkdir()
        (self.home / ".zshrc").write_text("# original\n")
        result = self.bash("install_shell")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("自定义 ZDOTDIR", result.stderr)
        self.assertEqual((self.home / ".zshrc").read_text(), "# original\n")
        self.assertFalse((self.home / ".local/share/shellready/config/init.zsh").exists())

    @unittest.skipUnless(shutil.which("zsh"), "zsh unavailable")
    def test_login_profile_output_does_not_pollute_zdotdir_probe(self):
        (self.home / ".zprofile").write_text("print -r -- login-banner\n")
        (self.home / ".zlogin").write_text("print -r -- after-profile-banner\n")
        result = self.assert_success("install_shell")
        self.assertIn("login-banner", result.stdout + result.stderr)
        self.assertIn("after-profile-banner", result.stdout + result.stderr)
        self.assertIn("# >>> ShellReady >>>", (self.home / ".zshrc").read_text())

    def test_update_repairs_empty_block_in_place_without_duplicate_backups(self):
        (self.home / ".zshrc").write_text(
            "# before\n# >>> ShellReady >>>\n# <<< ShellReady <<<\n# after\n")
        self.assert_success('''
if shell_block_is_current "$HOME/.zshrc"; then exit 99; fi
add_shell_block "$HOME/.zshrc"
shell_block_is_current "$HOME/.zshrc" || exit 1
add_shell_block "$HOME/.zshrc"
''')
        content = (self.home / ".zshrc").read_text()
        self.assertIn('source "$HOME/.local/share/shellready/config/init.zsh"', content)
        self.assertTrue(content.startswith("# before\n"))
        self.assertTrue(content.endswith("# after\n"))
        self.assertEqual(content.count("# >>> ShellReady >>>"), 1)
        backups = list((self.home / ".local/state/shellready/backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertIn("# >>> ShellReady >>>\n# <<< ShellReady <<<", backups[0].read_text())

    def test_status_helper_rejects_truncated_block(self):
        (self.home / ".zshrc").write_text("# >>> ShellReady >>>\n")
        result = self.bash('shell_block_is_current "$HOME/.zshrc"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("接入段损坏", result.stderr)

    def test_uninstall_restores_shell_with_usr_bin_zsh_alias(self):
        # getent, /etc/shells lookup and chsh are stubs; never change an account.
        self.assert_success('''
printf /bin/bash > "$STATE/original-shell"
getent() { printf 'fixture:x:123:123::%s:/usr/bin/zsh\\n' "$HOME"; }
grep() { return 0; }
chsh() { printf '%s\\n' "$*" > "$WORK/chsh-called"; }
uninstall_shell
[[ $(cat "$WORK/chsh-called") == "-s /bin/bash $TARGET_USER" ]] || exit 1
[[ ! -e "$STATE/original-shell" ]] || exit 1
''')


if __name__ == "__main__":
    unittest.main()
