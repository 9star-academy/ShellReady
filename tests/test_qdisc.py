"""Queue transactions use fake tc/ip/sysctl; no host interface is modified."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CODEL = {'kind': 'fq_codel', 'handle': '0:', 'root': True,
         'options': {'limit': 10240, 'flows': 1024, 'quantum': 1514,
                     'target': 5000, 'interval': 100000, 'memory_limit': 33554432,
                     'ecn': True, 'drop_batch': 64}}


class QdiscTests(unittest.TestCase):
    def run_case(self, body, queues=None):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'queues.json').write_text(json.dumps(queues or [CODEL]))
            (work / 'tc').write_text(r'''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ['WORK']); args = sys.argv[1:]
q = json.loads((p/'queues.json').read_text())
if args[:3] == ['-j','qdisc','show']:
    print(json.dumps(q)); sys.exit(0)
if args[:2] == ['filter', 'show']:
    if (p/'filters').exists(): print('filter custom')
    sys.exit(0)
if args[:2] == ['qdisc','show']:
    print(json.dumps(q)); sys.exit(0)
if args[:2] == ['qdisc','replace']:
    with (p/'tc-writes').open('a') as f: f.write(' '.join(args)+'\n')
    if (p/'deny-tc').exists(): sys.exit(1)
    if (p/'deny-second-tc').exists() and len((p/'tc-writes').read_text().splitlines()) == 2: sys.exit(1)
    parent = args[5] if args[4] == 'parent' else None
    kind_index = 6 if parent else 5
    if args[kind_index] == 'handle': kind_index += 2
    kind = args[kind_index]
    for item in q:
        if (parent and item.get('parent') == parent) or (not parent and item.get('root')):
            item['kind'] = kind
            item['handle'] = '8001:' if kind == 'fq' else '0:'
            item['options'] = {'limit': 10000} if kind == 'fq' else json.loads(os.environ['ORIGINAL_OPTIONS'])
    (p/'queues.json').write_text(json.dumps(q)); sys.exit(0)
sys.exit(2)
''')
            (work / 'tc').chmod(0o755)
            script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/bbr.sh"
source "$ROOT/modules/qdisc.sh"
QDISC_FILE="$WORK/etc/90-shellready-fq.conf"; QDISC_STATE="$WORK/qdisc-state"
SYSCTL_FILE="$WORK/etc/90-shellready-bbr.conf"; BBR_STATE="$WORK/bbr-state"
BBR_SYSCTL_DIRS=("$WORK/etc"); BBR_SYSCTL_MAIN="$WORK/sysctl.conf"
mkdir -p "$WORK/etc"
printf fq_codel > "$WORK/default"; printf cubic > "$WORK/algo"
sha256sum() { shasum -a 256 "$@"; }
sysctl() {
    case "$*" in
    '-n net.core.default_qdisc') cat "$WORK/default";;
    '-n net.ipv4.tcp_available_congestion_control') echo 'reno cubic bbr';;
    '-n net.ipv4.tcp_congestion_control') cat "$WORK/algo";;
    '-w net.core.default_qdisc='*) printf '%s' "${2#*=}" > "$WORK/default";;
    '-w net.ipv4.tcp_congestion_control='*) printf '%s' "${2#*=}" > "$WORK/algo";;
    *) return 1;;
    esac
}
ip() { if [[ "$*" == '-o route show default' ]]; then echo 'default via 1.2.3.4 dev eth0'; fi; }
modprobe() { :; }
RESULTS=(); FAILED=0; SKIPPED=0
'''
            result = subprocess.run(['bash', '-c', script + body], text=True, errors='replace',
                                    capture_output=True, timeout=10,
                                    env={**os.environ, 'WORK': tmp, 'ROOT': str(ROOT),
                                         'PATH': tmp + ':' + os.environ['PATH'],
                                         'ORIGINAL_OPTIONS': json.dumps(next((q['options'] for q in (queues or [CODEL]) if q['kind'] == 'fq_codel'), CODEL['options']))})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_install_repeat_and_restore_runtime_and_persistent_defaults(self):
        self.run_case(r'''
install_bbr_fq
[[ $(cat "$WORK/default") == fq && $(cat "$WORK/algo") == bbr && -f "$QDISC_FILE" ]] || exit 99
install_bbr_fq
restore_qdisc
restore_bbr
[[ $(cat "$WORK/default") == fq_codel && $(cat "$WORK/algo") == cubic && ! -e "$QDISC_FILE" ]] || exit 99
jq -e '.[0].kind == "fq_codel"' "$WORK/queues.json" >/dev/null
''')

    def test_custom_queue_skips_without_changing_bbr(self):
        self.run_case(r'''
rc=0; install_bbr_fq || rc=$?
[[ "$rc" == 2 && ! -e "$WORK/tc-writes" && ! -e "$SYSCTL_FILE" && ! -e "$QDISC_FILE" ]] || exit 99
''', [{'kind': 'htb', 'handle': '1:', 'root': True, 'options': {}}])

    def test_existing_filters_skip_without_any_changes(self):
        self.run_case(r'''
touch "$WORK/filters"
rc=0; install_bbr_fq || rc=$?
[[ "$rc" == 2 && ! -e "$WORK/tc-writes" && ! -e "$SYSCTL_FILE" ]] || exit 99
''')

    def test_multiqueue_preserves_root_and_changes_only_leaf(self):
        leaf = {**CODEL, 'root': False, 'parent': ':1'}
        self.run_case(r'''
install_bbr_fq
jq -e '.[0].kind == "mq" and .[1].kind == "fq"' "$WORK/queues.json" >/dev/null
! grep -q 'root' "$WORK/tc-writes" || exit 99
restore_qdisc
jq -e '.[0].kind == "mq" and .[1].kind == "fq_codel"' "$WORK/queues.json" >/dev/null
''', [{'kind': 'mq', 'handle': '0:', 'root': True}, leaf])

    def test_failed_queue_change_cleans_state_and_preserves_bbr(self):
        self.run_case(r'''
touch "$WORK/deny-tc"
rc=0; install_bbr_fq || rc=$?
[[ "$rc" == 1 && $(cat "$WORK/default") == fq_codel && $(cat "$WORK/algo") == cubic && ! -e "$QDISC_STATE" ]] || exit 99
''')

    def test_later_queue_conflict_skips_before_mutation(self):
        self.run_case(r'''
printf 'net.core.default_qdisc = fq_codel\n' > "$WORK/etc/99-provider.conf"
rc=0; install_bbr_fq || rc=$?
[[ "$rc" == 2 && ! -e "$WORK/tc-writes" && ! -e "$SYSCTL_FILE" ]] || exit 99
''')

    def test_restore_refuses_later_configuration_edits(self):
        self.run_case(r'''
install_bbr_fq
printf '# user edit\n' >> "$QDISC_FILE"
if restore_qdisc; then exit 99; fi
[[ $(cat "$WORK/default") == fq && -e "$QDISC_STATE" ]] || exit 99
''')

    def test_restore_refuses_later_runtime_queue_changes(self):
        self.run_case(r'''
install_bbr_fq
printf '[{"kind":"cake","handle":"1:","root":true}]' > "$WORK/queues.json"
if restore_qdisc; then exit 99; fi
[[ $(cat "$WORK/default") == fq && -e "$QDISC_STATE" ]] || exit 99
''')

    def test_codel_without_ecn_is_restored_with_noecn(self):
        queue = {**CODEL, 'options': {k: v for k, v in CODEL['options'].items() if k != 'ecn'}}
        self.run_case(r'''
install_bbr_fq
restore_qdisc
 grep -q 'fq_codel noecn' "$WORK/tc-writes" || exit 99
''', [queue])

    def test_reboot_handle_change_does_not_prevent_semantic_restore(self):
        self.run_case(r'''
install_bbr_fq
jq '.[0].handle = "0:"' "$WORK/queues.json" > "$WORK/reboot.json"
mv "$WORK/reboot.json" "$WORK/queues.json"
restore_qdisc
[[ ! -e "$QDISC_STATE" ]] || exit 99
''')

    def test_new_filters_prevent_restore(self):
        self.run_case(r'''
install_bbr_fq
touch "$WORK/filters"
if restore_qdisc; then exit 99; fi
[[ $(cat "$WORK/default") == fq && -e "$QDISC_STATE" ]] || exit 99
''')

    def test_builtin_fq_does_not_require_loadable_module(self):
        self.run_case(r'''
modprobe() { return 1; }
install_bbr_fq
[[ $(cat "$WORK/default") == fq && $(cat "$WORK/algo") == bbr ]] || exit 99
''')

    def test_missing_dependency_is_reported_before_mutation(self):
        self.run_case(r'''
command() { if [[ "$*" == '-v tc' ]]; then return 1; else builtin command "$@"; fi; }
rc=0; install_bbr_fq || rc=$?
[[ "$rc" == 1 && ! -e "$QDISC_STATE" && ! -e "$WORK/tc-writes" ]] || exit 99
''')

    def test_failed_restore_can_be_retried(self):
        self.run_case(r'''
install_bbr_fq
touch "$WORK/deny-tc"
if restore_qdisc; then exit 99; fi
[[ -f "$QDISC_FILE" && -e "$QDISC_STATE" ]] || exit 99
rm "$WORK/deny-tc"
restore_qdisc
[[ ! -e "$QDISC_STATE" && $(cat "$WORK/default") == fq_codel ]] || exit 99
''')

    def test_partial_multiqueue_failure_restores_changed_leaf(self):
        leaf1 = {**CODEL, 'root': False, 'parent': ':1'}
        leaf2 = {**CODEL, 'root': False, 'parent': ':2'}
        self.run_case(r'''
touch "$WORK/deny-second-tc"
rc=0; install_bbr_fq || rc=$?
[[ "$rc" == 1 && ! -e "$QDISC_STATE" && $(cat "$WORK/default") == fq_codel ]] || exit 99
jq -e '.[0].kind == "mq" and .[1].kind == "fq_codel" and .[2].kind == "fq_codel"' "$WORK/queues.json" >/dev/null
''', [{'kind': 'mq', 'handle': '0:', 'root': True}, leaf1, leaf2])

    def test_bbr_persistence_failure_cannot_report_fq_success(self):
        self.run_case(r'''
install() {
    local destination=''
    for destination; do :; done
    if [[ "$destination" == "$SYSCTL_FILE" ]]; then return 1; fi
    command install "$@"
}
rc=0; install_bbr_fq || rc=$?
[[ "$rc" == 1 && $(cat "$WORK/algo") == cubic ]] || exit 99
[[ $(cat "$WORK/default") == fq_codel && ! -e "$QDISC_STATE" && ! -e "$QDISC_FILE" ]] || exit 99
''')
