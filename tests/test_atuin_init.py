"""Check Atuin integration in a real Zsh with an isolated HOME and CLI fixture."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("zsh"), "requires zsh")
class AtuinInitTests(unittest.TestCase):
    def test_history_setup_preserves_question_mark(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary = home / ".local/share/shellready/bin/atuin"
            binary.parent.mkdir(parents=True)
            # Atuin v18.22.0 enables its AI question-mark widget unless disabled.
            # Capture the actual arguments passed by our real Zsh integration.
            binary.write_text("""#!/bin/sh
printf '%s\\n' "$@" > "$ATUIN_TEST_ARGS"
for argument in "$@"; do
    [ "$argument" != --disable-ai ] || exit 0
done
cat <<'EOF'
self-atuin-ai-question-mark() { :; }
zle -N self-atuin-ai-question-mark
bindkey '?' self-atuin-ai-question-mark
EOF
""")
            binary.chmod(0o755)
            captured = home / "atuin-arguments"
            process = subprocess.run(
                ["zsh", "-dfi", "-c", """
bindkey -e
before=$(bindkey '?')
source "$SHELLREADY_TEST_INIT"
after=$(bindkey '?')
print -r -- "$before"
print -r -- "$after"
"""],
                env={
                    **os.environ,
                    "HOME": str(home),
                    "ZDOTDIR": str(home),
                    "SHELLREADY_TEST_INIT": str(ROOT / "config/init.zsh"),
                    "ATUIN_TEST_ARGS": str(captured),
                },
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            bindings = process.stdout.splitlines()
            self.assertEqual(len(bindings), 2, process.stdout + process.stderr)
            self.assertEqual(bindings[0], bindings[1], "Atuin changed the ? key")
            arguments = captured.read_text().splitlines()
            self.assertEqual(arguments[:2], ["init", "zsh"])
            self.assertIn("--disable-up-arrow", arguments)
            self.assertIn("--disable-ai", arguments)


if __name__ == "__main__":
    unittest.main()
