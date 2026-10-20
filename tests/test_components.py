"""Component lifecycle preserves other tools, configuration and user data."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ComponentTests(unittest.TestCase):
    def run_case(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            prelude = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/tools.sh"
source "$ROOT/modules/components.sh"
TARGET_HOME="$WORK/home"; TARGET_USER=$(id -un); ARCH=x86_64
PREFIX="$TARGET_HOME/.local/share/shellready"; STATE="$TARGET_HOME/.local/state/shellready"
as_user() { env HOME="$TARGET_HOME" "$@"; }
mkdir -p "$PREFIX/bin" "$PREFIX/config/atuin" "$STATE" "$WORK"
touch "$PREFIX/.shellready"
fixture_tool() {
    local tool=$1 binary dir hash
    hash=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    dir="$PREFIX/tools/$tool-1.0-${hash:0:12}"
    mkdir -p "$dir"
    printf '%s\n' "$hash" > "$dir/.complete"
    for binary in $(component_binaries "$tool"); do
        printf '#!/bin/sh\necho fixture\n' > "$dir/$binary"
        chmod +x "$dir/$binary"
        ln -s "$dir/$binary" "$PREFIX/bin/$binary"
    done
}
'''
            result = subprocess.run(['bash', '-c', prelude + body], capture_output=True,
                                    text=True, timeout=8,
                                    env={**os.environ, 'ROOT': str(ROOT), 'WORK': tmp})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_disable_enable_preserves_other_component_and_data(self):
        self.run_case(r'''
fixture_tool atuin; fixture_tool starship
printf keep > "$PREFIX/config/atuin/config.toml"
COMPONENT=atuin; OPERATION=disable; manage_component
[[ -f "$PREFIX/config/disabled/atuin" && -x "$PREFIX/bin/starship" ]] || exit 99
OPERATION=enable; manage_component
[[ ! -e "$PREFIX/config/disabled/atuin" && $(cat "$PREFIX/config/atuin/config.toml") == keep ]] || exit 99
''')

    def test_trzsz_disable_hides_both_commands_and_enable_restores(self):
        self.run_case(r'''
fixture_tool trzsz
COMPONENT=trzsz; OPERATION=disable; manage_component
[[ ! -e "$PREFIX/bin/trz" && ! -L "$PREFIX/bin/tsz" ]] || exit 99
component_installed trzsz || exit 99
OPERATION=enable; manage_component
[[ -x "$PREFIX/bin/trz" && -x "$PREFIX/bin/tsz" ]] || exit 99
''')

    def test_remove_only_selected_owned_tool_and_preserves_settings(self):
        self.run_case(r'''
fixture_tool atuin; fixture_tool zoxide
printf keep > "$PREFIX/config/atuin/config.toml"
COMPONENT=atuin; OPERATION=remove; manage_component
[[ ! -e "$PREFIX/bin/atuin" && -x "$PREFIX/bin/zoxide" ]] || exit 99
[[ $(cat "$PREFIX/config/atuin/config.toml") == keep && -f "$PREFIX/.shellready" ]] || exit 99
! component_installed atuin || exit 99
''')

    def test_unmanaged_entry_is_not_removed(self):
        self.run_case(r'''
printf mine > "$PREFIX/bin/atuin"
COMPONENT=atuin; OPERATION=remove
if manage_component; then exit 99; fi
[[ $(cat "$PREFIX/bin/atuin") == mine ]] || exit 99
''')

    def test_enable_missing_tool_does_not_install_or_write(self):
        self.run_case(r'''
COMPONENT=atuin; OPERATION=enable
rc=0; manage_component || rc=$?
[[ "$rc" != 0 && ! -e "$PREFIX/config/disabled" ]] || exit 99
''')

    def test_single_install_does_not_install_other_tools_or_enable_disabled(self):
        self.run_case(r'''
install_dependencies() { :; }; install_manager() { :; }; install_shell() { :; }
install_tool() { fixture_tool "$1"; }
mkdir -p "$PREFIX/config/disabled"; touch "$PREFIX/config/disabled/atuin"
COMPONENT=atuin; OPERATION=install; manage_component
[[ -x "$PREFIX/bin/atuin" && ! -e "$PREFIX/bin/starship" && -f "$PREFIX/config/disabled/atuin" ]] || exit 99
''')

    def test_zsh_does_not_initialize_disabled_tools(self):
        self.run_case(r'''
fixture_tool starship; fixture_tool atuin; fixture_tool zoxide; fixture_tool suggestions
mkdir -p "$PREFIX/config/disabled"
for tool in starship atuin zoxide suggestions; do touch "$PREFIX/config/disabled/$tool"; done
for binary in starship atuin zoxide; do
    printf '#!/bin/sh\necho called >> "$HOME/called"\n' > "$(readlink "$PREFIX/bin/$binary")"
done
printf 'print called >> "$HOME/called"\n' > "$(readlink "$PREFIX/bin/zsh-autosuggestions.zsh")"
HOME="$TARGET_HOME" zsh -dfi -c 'source "$ROOT/config/init.zsh"' </dev/null
[[ ! -e "$TARGET_HOME/called" ]] || exit 99
''')

    def test_repair_existing_does_not_reinstall_removed_components(self):
        self.run_case(r'''
fixture_tool zoxide
install_dependencies() { :; }; install_manager() { :; }; install_shell() { :; }
install_tool() { printf '%s\n' "$1" >> "$WORK/installed"; }
RESULTS=(); FAILED=0; SKIPPED=0; SKIP_BBR=1
repair_components
[[ $(cat "$WORK/installed") == zoxide ]] || exit 99
''')

    def test_checksum_failure_in_single_install_never_initializes_shell(self):
        self.run_case(r'''
install_dependencies() { :; }; install_manager() { :; }
download() { printf untrusted > "$2"; }
verify_sha256() { return 1; }
install_shell() { touch "$WORK/shell-activated"; }
COMPONENT=atuin; OPERATION=install
if manage_component; then exit 99; fi
[[ ! -e "$WORK/shell-activated" && ! -e "$PREFIX/bin/atuin" ]] || exit 99
''')

    def test_missing_active_link_is_reported_as_incomplete(self):
        self.run_case(r'''
fixture_tool atuin
rm "$PREFIX/bin/atuin"
rc=0; component_status atuin || rc=$?
[[ "$rc" == 2 ]] || exit 99
''')

    def test_full_installer_tool_path_preserves_disabled_trzsz(self):
        self.run_case(r'''
IFS=$'\t' read -r _ version _ _ hash < <(awk -F '\t' '$1=="trzsz" && $3=="x86_64" {print}' "$ROOT/config/assets.tsv")
dir="$PREFIX/tools/trzsz-$version-${hash:0:12}"
mkdir -p "$dir" "$PREFIX/config/disabled"
printf '%s\n' "$hash" > "$dir/.complete"
for binary in trz tsz; do
    printf '#!/bin/sh\necho fixture\n' > "$dir/$binary"; chmod +x "$dir/$binary"
done
touch "$PREFIX/config/disabled/trzsz"
install_trzsz
[[ ! -e "$PREFIX/bin/trz" && ! -L "$PREFIX/bin/tsz" ]] || exit 99
''')

    def test_trzsz_enable_uses_complete_installed_version(self):
        self.run_case(r'''
fixture_tool trzsz
COMPONENT=trzsz; OPERATION=disable; manage_component
IFS=$'\t' read -r _ version _ _ hash < <(awk -F '\t' '$1=="trzsz" && $3=="x86_64" {print}' "$ROOT/config/assets.tsv")
dir="$PREFIX/tools/trzsz-$version-${hash:0:12}"
mkdir -p "$dir"; printf '%s\n' "$hash" > "$dir/.complete"
OPERATION=enable; manage_component
[[ -x "$PREFIX/bin/trz" && -x "$PREFIX/bin/tsz" ]] || exit 99
''')

    def test_batch_repair_initializes_shell_only_after_all_tool_repairs(self):
        self.run_case(r'''
fixture_tool starship; fixture_tool atuin
install_dependencies() { :; }; install_manager() { :; }
install_tool() {
    printf '%s\n' "$1" >> "$WORK/repaired"
    if [[ "$1" == atuin ]]; then touch "$WORK/atuin-repaired"; fi
}
install_shell() {
    printf 'shell\n' >> "$WORK/repaired"
    [[ -f "$WORK/atuin-repaired" ]] || return 1
}
RESULTS=(); FAILED=0; SKIPPED=0; SKIP_BBR=1
repair_components
[[ "$FAILED" == 0 ]] || exit 99
[[ $(cat "$WORK/repaired") == $'starship\natuin\nshell' ]] || exit 99
''')
