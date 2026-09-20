"""Isolated checks for BBR persistence ordering and failed-write recovery."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BBRRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def success(self, body):
        prelude = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/bbr.sh"
SYSCTL_FILE="$WORK/etc/90-shellready-bbr.conf"; BBR_STATE="$WORK/state"
BBR_SYSCTL_DIRS=("$WORK/etc" "$WORK/run" "$WORK/usr")
BBR_SYSCTL_MAIN="$WORK/sysctl.conf"
mkdir -p "${BBR_SYSCTL_DIRS[@]}"
printf cubic > "$WORK/algo"
RESULTS=(); FAILED=0; SKIPPED=0
sha256sum() { shasum -a 256 "$@"; }
sysctl() {
    case "$*" in
        '-n net.ipv4.tcp_available_congestion_control') echo 'reno cubic bbr';;
        '-n net.ipv4.tcp_congestion_control') cat "$WORK/algo";;
        '-w '*)
            printf '%s\n' "$*" >> "$WORK/writes"
            [[ ${DENY_WRITE:-0} == 0 ]] || return 1
            printf '%s' "${2#*=}" > "$WORK/algo";;
    esac
}
'''
        result = subprocess.run(['bash', '-c', prelude + body],
                                env={**os.environ, 'ROOT': str(ROOT), 'WORK': self.tmp.name},
                                text=True, errors='replace', capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_later_conflict_skips_before_any_write(self):
        self.success(r'''
printf 'net.ipv4.tcp_congestion_control = cubic\n' > "$WORK/etc/99-provider.conf"
run_step bbr install_bbr
[[ "$SKIPPED" == 1 && "$FAILED" == 0 && ! -e "$SYSCTL_FILE" && ! -e "$WORK/writes" ]] || exit 99
''')

    def test_earlier_conflict_is_overridden_by_managed_file(self):
        self.success(r'''
printf 'net.ipv4.tcp_congestion_control = cubic\n' > "$WORK/etc/10-provider.conf"
run_step bbr install_bbr
[[ "$SKIPPED" == 0 && "$FAILED" == 0 && $(cat "$WORK/algo") == bbr ]] || exit 99
''')

    def test_last_explicit_assignment_wins(self):
        self.success(r'''
printf 'net.ipv4.tcp_congestion_control = cubic\n' > "$WORK/etc/99-provider.conf"
printf 'net.ipv4.tcp_congestion_control = bbr\n' > "$WORK/etc/zz-local.conf"
run_step bbr install_bbr
[[ "$SKIPPED" == 0 && "$FAILED" == 0 ]] || exit 99
''')

    def test_higher_priority_directory_masks_same_basename(self):
        self.success(r'''
printf 'net.ipv4.tcp_congestion_control = bbr\n' > "$WORK/etc/99-provider.conf"
printf 'net.ipv4.tcp_congestion_control = cubic\n' > "$WORK/usr/99-provider.conf"
run_step bbr install_bbr
[[ "$SKIPPED" == 0 && "$FAILED" == 0 ]] || exit 99
''')

    def test_main_sysctl_conf_can_override_procps_system_reload(self):
        self.success(r'''
printf 'net.ipv4.tcp_congestion_control = cubic\n' > "$BBR_SYSCTL_MAIN"
run_step bbr install_bbr
[[ "$SKIPPED" == 1 && ! -e "$SYSCTL_FILE" ]] || exit 99
''')

    def test_slash_key_and_ignored_error_prefix_are_detected(self):
        self.success(r'''
printf '# header\n-net/ipv4/tcp_congestion_control = reno\n' > "$WORK/etc/99-provider.conf"
run_step bbr install_bbr
[[ "$SKIPPED" == 1 && ! -e "$SYSCTL_FILE" ]] || exit 99
''')

    def test_failed_apply_cleans_record_without_rewriting_unchanged_runtime(self):
        self.success(r'''
DENY_WRITE=1
run_step bbr install_bbr
[[ "$FAILED" == 1 && ! -e "$SYSCTL_FILE" && ! -e "$BBR_STATE" ]] || exit 99
[[ $(wc -l < "$WORK/writes" | tr -d ' ') == 1 ]] || exit 99
[[ $(cat "$WORK/algo") == cubic ]] || exit 99
''')

    def test_status_reports_later_persistence_conflict(self):
        self.success(r'''
install_bbr
printf 'net.ipv4.tcp_congestion_control = cubic\n' > "$WORK/etc/99-provider.conf"
run_step status status_bbr
[[ "$SKIPPED" == 1 && "$FAILED" == 0 ]] || exit 99
''')


if __name__ == '__main__':
    unittest.main()
