"""Platform checks with mocked OS metadata; no host configuration is changed."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlatformTests(unittest.TestCase):
    def check(self, distro='ubuntu', version='26.04', machine='x86_64',
              system='Linux', kernel=False, container=False):
        script = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/kernel.sh"
uname() {
    case "$1" in
        -s) printf '%s\n' "$TEST_SYSTEM" ;;
        -m) printf '%s\n' "$TEST_MACHINE" ;;
        *) return 1 ;;
    esac
}
source() {
    [[ "$1" == /etc/os-release ]] || return 1
    ID=$TEST_DISTRO
    VERSION_ID=$TEST_VERSION
    PRETTY_NAME="$ID $VERSION_ID"
}
systemd-detect-virt() { [[ "$TEST_CONTAINER" == 1 ]]; }
update-grub() { echo unexpected-update-grub; return 99; }
verify_or_repair_kernel_boot() { echo checked-existing-boot; }
df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted\nfixture 3000000 0 3000000 0%% /boot\n'; }
mokutil() { echo 'SecureBoot disabled'; }
check_platform
printf 'ARCH=%s\n' "$ARCH"
if [[ "$TEST_KERNEL" == 1 ]]; then
    case "$ARCH" in x86_64) TAG=x86_64-7.2.6 ;; aarch64) TAG=arm64-7.2.6 ;; esac
    kernel_preflight
    echo preflight-passed
fi
'''
        return subprocess.run(
            ['bash', '-c', script], capture_output=True, text=True,
            env={**os.environ, 'ROOT': str(ROOT), 'TEST_DISTRO': distro,
                 'TEST_VERSION': version, 'TEST_MACHINE': machine,
                 'TEST_SYSTEM': system, 'TEST_KERNEL': '1' if kernel else '0',
                 'TEST_CONTAINER': '1' if container else '0'})

    def test_supported_releases_and_architectures(self):
        for distro, version in [('ubuntu', '22.04'), ('ubuntu', '24.04'),
                                ('ubuntu', '24.10'), ('ubuntu', '25.04'),
                                ('ubuntu', '26.04'), ('ubuntu', '26.10'),
                                ('ubuntu', '28.04'), ('debian', '12'),
                                ('debian', '12.1'), ('debian', '13'),
                                ('debian', '14')]:
            for machine, arch in [('x86_64', 'x86_64'), ('aarch64', 'aarch64'),
                                  ('arm64', 'aarch64')]:
                with self.subTest(distro=distro, version=version, machine=machine):
                    result = self.check(distro, version, machine)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), f'ARCH={arch}')

    def test_unsupported_releases_are_rejected(self):
        for distro, version in [('ubuntu', '20.04'), ('ubuntu', '22.10'),
                                ('ubuntu', '24.03'), ('ubuntu', ''),
                                ('ubuntu', 'unknown'), ('ubuntu', '26.04-dev'),
                                ('debian', '11'), ('debian', ''),
                                ('debian', 'testing'), ('fedora', '44'),
                                ('linuxmint', '26')]:
            with self.subTest(distro=distro, version=version):
                result = self.check(distro, version)
                self.assertEqual(result.returncode, 1)
                self.assertIn('不支持', result.stderr)
                self.assertNotIn('ARCH=', result.stdout)

    def test_non_linux_is_rejected(self):
        result = self.check(system='Darwin')
        self.assertEqual(result.returncode, 1)
        self.assertIn('安装目标必须是 Linux', result.stderr)

    def test_unsupported_architecture_is_rejected(self):
        result = self.check(machine='riscv64')
        self.assertEqual(result.returncode, 1)
        self.assertIn('仅支持 x86_64 / ARM64', result.stderr)

    def test_kernel_accepts_minimum_and_newer_releases_on_both_architectures(self):
        for distro, version in [('ubuntu', '24.04'), ('ubuntu', '24.10'),
                                ('ubuntu', '26.04'), ('ubuntu', '26.10'),
                                ('ubuntu', '28.04'), ('debian', '12'),
                                ('debian', '13'), ('debian', '14')]:
            for machine in ('x86_64', 'aarch64'):
                with self.subTest(distro=distro, version=version, machine=machine):
                    result = self.check(distro, version, machine, kernel=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('checked-existing-boot', result.stdout)
                    self.assertIn('preflight-passed', result.stdout)
                    self.assertNotIn('unexpected-update-grub', result.stdout)

    def test_ubuntu_22_04_still_allows_tools_but_rejects_kernel_upgrade(self):
        result = self.check(version='22.04', kernel=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('ARCH=x86_64', result.stdout)
        self.assertIn('Ubuntu 24.04+、Debian 12+', result.stderr)
        self.assertNotIn('checked-existing-boot', result.stdout)

    def test_newer_release_still_rejects_container_kernel_upgrade(self):
        result = self.check(kernel=True, container=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('容器共享宿主内核', result.stderr)
        self.assertNotIn('checked-existing-boot', result.stdout)


if __name__ == '__main__':
    unittest.main()
