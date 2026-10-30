"""Run the real status CLI against an isolated user and mock kernel readings."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StatusTests(unittest.TestCase):
    def test_valid_zsh_files_do_not_hide_a_bash_login_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/shell.sh"
TARGET_HOME="$TEST_HOME"; PREFIX="$TARGET_HOME/prefix"
LOGIN_SHELL=/bin/bash
mkdir -p "$PREFIX/config"
shell_block > "$TARGET_HOME/.zshrc"
printf '# fixture\n' > "$PREFIX/config/init.zsh"
eval "$(sed -n '/^status_shell() {/,/^}/p' "$ROOT/install.sh")"
status_shell
'''
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                    env={**os.environ, 'ROOT': str(ROOT), 'TEST_HOME': tmp})
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('登录 Shell 仍为 /bin/bash', result.stdout)
            self.assertIn('shellready repair', result.stdout)

    def test_status_rejects_empty_shell_block_without_changing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            repo = work / "repo"
            repo.mkdir()
            shutil.copy(ROOT / "install.sh", repo)
            shutil.copy(ROOT / "bootstrap.sh", repo)
            for name in ("lib", "modules"):
                shutil.copytree(ROOT / name, repo / name)
            # Only the platform/user boundary is substituted. The CLI dispatcher,
            # status functions, result aggregation and exit codes run unchanged.
            with (repo / "lib/common.sh").open("a") as common:
                common.write('''
check_platform() { ARCH=x86_64; }
resolve_user() {
    TARGET_HOME="$TEST_HOME"; PREFIX="$TARGET_HOME/.local/share/shellready"
    STATE="$TARGET_HOME/.local/state/shellready"; LOGIN_SHELL=/bin/zsh
    KERNEL_STATE="$TEST_HOME/no-kernels"; SYSCTL_FILE="$TEST_HOME/no-bbr.conf"
}
as_user() { "$@"; }
sysctl() { echo bbr; }
modinfo() { echo 3; }
''')
            home = work / "home"
            prefix = home / ".local/share/shellready"
            (prefix / "bin").mkdir(parents=True)
            (prefix / "config").mkdir()
            (prefix / "config/init.zsh").write_text("# fixture\n")
            (prefix / "bin/zsh-autosuggestions.zsh").write_text("# fixture\n")
            for tool in ("trz", "tsz", "starship", "atuin", "zoxide"):
                binary = prefix / "bin" / tool
                binary.write_text("#!/bin/sh\necho fixture\n")
                binary.chmod(0o755)
            rc = home / ".zshrc"
            original = "# before\n# >>> ShellReady >>>\n# <<< ShellReady <<<\n# after\n"
            rc.write_text(original)
            result = subprocess.run(["bash", str(repo / "install.sh"), "status"],
                                    env={**os.environ, "TEST_HOME": str(home)},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("Zsh 接入段缺失或无效", result.stdout)
            self.assertEqual(rc.read_text(), original)
            self.assertFalse((home / ".local/state").exists())


if __name__ == "__main__":
    unittest.main()
