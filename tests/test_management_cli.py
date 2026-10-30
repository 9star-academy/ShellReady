"""Reuse the existing isolated CLI boundary to test new dispatch routes."""
import unittest
import os
import subprocess
import test_install_guidance as guidance
import test_entry_transitions as transitions


class ManagementCLITests(unittest.TestCase):
    def setUp(self):
        self.fixture = guidance.InstallGuidanceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_single_install_only_dispatches_selected_tool(self):
        with (self.fixture.repo / 'modules/tools.sh').open('a') as f:
            f.write('\ninstall_tool() { echo "tool:$1" >> "$TEST_WORK/calls"; }\n')
        result = self.fixture.run_install('component', 'atuin', 'install', '--skip-bbr')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.fixture.work / 'calls').read_text().splitlines(),
                         ['install_manager', 'tool:atuin', 'install_shell'])
        self.assertEqual((self.fixture.work / 'algo').read_text(), 'cubic')

    def test_sudo_receives_only_explicit_download_configuration(self):
        entry = self.fixture.repo / 'install.sh'
        entry.write_text(entry.read_text().replace('if false; then', 'if [[ "$READ_ONLY" == 0 ]]; then', 1))
        sudo = self.fixture.work / 'bin/sudo'
        sudo.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_WORK/sudo-args"\n')
        sudo.chmod(0o755)
        env = {**os.environ, 'PATH': str(sudo.parent) + os.pathsep + os.environ['PATH'],
               'TEST_WORK': str(self.fixture.work), 'SHELLREADY_DOWNLOAD_MODE': 'cn',
               'SHELLREADY_GITHUB_MIRROR': 'https://mirror.example/prefix'}
        result = subprocess.run(['bash', str(entry), '--keep-shell', '--skip-bbr'],
                                env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = (self.fixture.work / 'sudo-args').read_text().splitlines()
        self.assertEqual(args[:4], ['env', 'SHELLREADY_DOWNLOAD_MODE=cn',
                                   'SHELLREADY_GITHUB_MIRROR=https://mirror.example/prefix', 'bash'])
        self.assertIn('--keep-shell', args)
        self.assertIn('--skip-bbr', args)

    def test_installed_manager_remembers_cn_but_accepts_explicit_override(self):
        fixture = transitions.EntryTransitionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.env.update(SHELLREADY_DOWNLOAD_MODE='cn', SHELLREADY_GITHUB_MIRROR='https://mirror.example')
        fixture.seed('atuin')
        fixture.run_cli('component', 'atuin', 'install', '--keep-shell')
        with (fixture.prefix / 'app/modules/update.sh').open('a') as f:
            f.write('\nself_update() { echo "CONFIG:$SHELLREADY_DOWNLOAD_MODE:$SHELLREADY_GITHUB_MIRROR"; }\n')
        fixture.env.pop('SHELLREADY_DOWNLOAD_MODE')
        fixture.env.pop('SHELLREADY_GITHUB_MIRROR')
        result = fixture.run_cli('self-update', manager=True)
        self.assertIn('CONFIG:cn:https://mirror.example', result.stdout)
        fixture.env['SHELLREADY_DOWNLOAD_MODE'] = 'direct'
        result = fixture.run_cli('self-update', manager=True)
        self.assertIn('CONFIG:direct:https://mirror.example', result.stdout)

    def test_standalone_bbr_does_not_install_terminal_tools(self):
        result = self.fixture.run_install('bbr-enable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.fixture.work / 'calls').exists())
        self.assertEqual((self.fixture.work / 'algo').read_text(), 'bbr')

    def test_readonly_missing_component_does_not_install_anything(self):
        result = self.fixture.run_install('component', 'atuin', 'status')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((self.fixture.work / 'calls').exists())
        self.assertFalse((self.fixture.work / 'lock').exists())

    def test_menu_and_bbr_menu_are_available_without_mutation_lock(self):
        # EOF returns immediately even without an interactive terminal.
        for action in ('menu', 'bbr-menu'):
            result = self.fixture.run_install(action)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.fixture.work / 'lock').exists())
        self.assertFalse((self.fixture.work / 'calls').exists())

    def test_self_update_delegates_before_outer_elevation_and_lock(self):
        with (self.fixture.repo / 'modules/update.sh').open('a') as module:
            module.write('\nself_update() { echo self-update >> "$TEST_WORK/calls"; }\n')
        result = self.fixture.run_install('self-update')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.fixture.work / 'calls').read_text().splitlines(), ['self-update'])
        self.assertFalse((self.fixture.work / 'lock').exists())

    def test_total_status_checks_existing_queue_management_records(self):
        # Resolve the paths after module globals have been sourced.
        with (self.fixture.repo / 'modules/qdisc.sh').open('a') as f:
            f.write('''\nQDISC_STATE="$TEST_WORK/qdisc-state"
status_qdisc() { echo queue-status >> "$TEST_WORK/calls"; return 2; }
''')
        (self.fixture.work / 'qdisc-state').mkdir()
        result = self.fixture.run_install('status')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('queue-status', (self.fixture.work / 'calls').read_text())

    def test_single_install_stops_when_dependency_refresh_fails(self):
        with (self.fixture.repo / 'lib/common.sh').open('a') as f:
            f.write('''\ndpkg-query() { return 1; }
apt-get() {
    printf 'apt:%s\\n' "$*" >> "$TEST_WORK/calls"
    if [[ "$1" == update ]]; then return 42; fi
}
''')
        with (self.fixture.repo / 'modules/tools.sh').open('a') as f:
            f.write('\ninstall_tool() { echo "tool:$1" >> "$TEST_WORK/calls"; }\n')
        result = self.fixture.run_install('component', 'atuin', 'install', '--skip-bbr')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((self.fixture.work / 'calls').read_text().splitlines(), ['apt:update'])

    def test_repair_reports_pending_fq_without_reapplying_queues(self):
        prefix = self.fixture.work / 'home/.local/share/shellready'
        prefix.mkdir(parents=True)
        (prefix / '.shellready').touch()
        with (self.fixture.repo / 'modules/qdisc.sh').open('a') as f:
            f.write('''\nQDISC_STATE="$TEST_WORK/qdisc-state"
status_qdisc() { echo queue-status >> "$TEST_WORK/calls"; return 2; }
install_bbr_fq() { echo unexpected-fq-reapply >> "$TEST_WORK/calls"; return 99; }
''')
        (self.fixture.work / 'qdisc-state').mkdir()
        result = self.fixture.run_install('repair')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        calls = (self.fixture.work / 'calls').read_text()
        self.assertIn('queue-status', calls)
        self.assertNotIn('unexpected-fq-reapply', calls)
