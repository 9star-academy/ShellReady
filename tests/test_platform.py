"""Platform checks with mocked OS metadata; no host configuration is changed."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlatformTests(unittest.TestCase):
    def check(self, distro='ubuntu', version='26.04', machine='x86_64',
              system='Linux', kernel=False):
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
check_platform
printf 'ARCH=%s\n' "$ARCH"
if [[ "$TEST_KERNEL" == 1 ]]; then
    TAG=x86_64-7.2.6
    kernel_preflight
fi
'''
        return subprocess.run(
            ['bash', '-c', script], capture_output=True, text=True,
            env={**os.environ, 'ROOT': str(ROOT), 'TEST_DISTRO': distro,
                 'TEST_VERSION': version, 'TEST_MACHINE': machine,
                 'TEST_SYSTEM': system, 'TEST_KERNEL': '1' if kernel else '0'})

    def test_supported_releases_and_architectures(self):
        for distro, version in [('ubuntu', '22.04'), ('ubuntu', '24.04'),
                                ('ubuntu', '26.04'), ('debian', '12'),
                                ('debian', '13')]:
            for machine, arch in [('x86_64', 'x86_64'), ('aarch64', 'aarch64'),
                                  ('arm64', 'aarch64')]:
                with self.subTest(distro=distro, version=version, machine=machine):
                    result = self.check(distro, version, machine)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), f'ARCH={arch}')

    def test_unsupported_releases_are_rejected(self):
        for distro, version in [('ubuntu', '20.04'), ('ubuntu', '26.10'),
                                ('ubuntu', ''), ('debian', '11'), ('fedora', '44')]:
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

    def test_ubuntu_26_04_keeps_optional_kernel_restriction(self):
        result = self.check(kernel=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('ARCH=x86_64', result.stdout)
        self.assertIn('可选内核仅允许 Ubuntu 24.04、Debian 12/13', result.stderr)


if __name__ == '__main__':
    unittest.main()
