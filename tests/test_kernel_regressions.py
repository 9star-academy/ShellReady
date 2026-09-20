"""Kernel recovery tests with all package and boot operations isolated in temp dirs."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KernelRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        tag = 'x86_64-7.2.6'
        name = 'linux-image-7.2.6-joeyblog-bbrv3_amd64.deb'
        (self.work / 'fixture.json').write_text(json.dumps({
            'tag_name': tag, 'draft': False, 'prerelease': False,
            'assets': [{'name': name, 'digest': 'sha256:' + 'a' * 64,
                        'browser_download_url': f'https://github.com/byJoey/Actions-bbr-v3/releases/download/{tag}/{name}'}],
        }))

    def bash(self, body):
        prelude = r'''set -euo pipefail
source "$ROOT/lib/common.sh"
source "$ROOT/modules/kernel.sh"
ARCH=x86_64; TAG=x86_64-7.2.6
KERNEL_STATE="$WORK/kernels"; KERNEL_BOOT_DIR="$WORK/boot"
RESULTS=(); FAILED=0; SKIPPED=0
mkdir -p "$KERNEL_BOOT_DIR/grub"
kernel_preflight() { :; }
apt-get() {
    printf 'apt-get %s\n' "$*" >> "$WORK/calls"
    [[ "$*" != *--no-remove* ]] || touch "$WORK/dpkg-installed"
}
download() {
    if [[ "$1" == *api.github.com* ]]; then cp "$WORK/fixture.json" "$2"; else touch "$2"; fi
}
verify_sha256() { :; }
dpkg-deb() { if [[ "$3" == Package ]]; then echo linux-image-7.2.6-joeyblog-bbrv3; else echo amd64; fi; }
dpkg() { printf 'dpkg %s\n' "$*" >> "$WORK/calls"; echo amd64; }
dpkg-query() { if [[ -f "$WORK/dpkg-installed" ]]; then echo 'install ok installed'; else return 1; fi; }
uname() { echo old-kernel; }
grub-script-check() { :; }
boot_fixture() {
    touch "$KERNEL_BOOT_DIR/vmlinuz-$1" "$KERNEL_BOOT_DIR/initrd.img-$1"
    printf "menuentry 'Linux' {\n linux /boot/vmlinuz-%s root=UUID=example\n initrd /boot/initrd.img-%s\n}\n" "$1" "$1" >> "$KERNEL_BOOT_DIR/grub/grub.cfg"
}
'''
        return subprocess.run(['bash', '-c', prelude + body],
                              env={**os.environ, 'ROOT': str(ROOT), 'WORK': str(self.work)},
                              capture_output=True, text=True, errors='replace')

    def success(self, body):
        result = self.bash(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_retry_repairs_grub_after_package_install_succeeded(self):
        self.success(r'''
boot_fixture old-kernel
kernel_preflight() { verify_or_repair_kernel_boot; }
update-grub() { echo grub-failed >> "$WORK/calls"; : > "$KERNEL_BOOT_DIR/grub/grub.cfg"; return 1; }
run_step first install_kernel
[[ "$FAILED" == 1 && -f "$WORK/dpkg-installed" && ! -e "$KERNEL_STATE/$TAG/installed" ]] || exit 99
update-grub() {
    echo grub-repaired >> "$WORK/calls"
    boot_fixture old-kernel
    boot_fixture 7.2.6-joeyblog-bbrv3
}
FAILED=0; SKIPPED=0
run_step retry install_kernel
[[ "$FAILED" == 0 && "$SKIPPED" == 1 && -f "$KERNEL_STATE/$TAG/installed" ]] || exit 99
[[ $(grep -c 'apt-get install -y --no-remove' "$WORK/calls") == 1 ]] || exit 99
grep -q grub-repaired "$WORK/calls" || exit 99
''')

    def test_first_install_does_not_rewrite_unverifiable_grub(self):
        self.success(r'''
boot_fixture old-kernel
: > "$KERNEL_BOOT_DIR/grub/grub.cfg"
update-grub() { echo unexpected > "$WORK/calls"; }
rc=0; verify_or_repair_kernel_boot || rc=$?
[[ "$rc" == 1 && ! -f "$WORK/calls" ]] || exit 99
''')

    def test_foreign_installed_package_is_not_adopted(self):
        self.success(r'''
touch "$WORK/dpkg-installed"
update-grub() { echo unexpected-grub >> "$WORK/calls"; }
run_step foreign install_kernel
[[ ! -d "$KERNEL_STATE/$TAG" ]] || exit 99
if grep -q unexpected-grub "$WORK/calls"; then exit 99; fi
''')

    def test_boot_check_rejects_missing_old_initramfs(self):
        self.success(r'''
boot_fixture old-kernel
rm "$KERNEL_BOOT_DIR/initrd.img-old-kernel"
rc=0; verify_kernel_boot old-kernel || rc=$?
[[ "$rc" == 1 ]] || exit 99
''')

    def test_boot_check_requires_matching_kernel_and_initrd_in_one_entry(self):
        self.success(r'''
boot_fixture old-kernel
printf "menuentry 'bad' {\n linux /boot/vmlinuz-old-kernel root=x\n initrd /boot/initrd.img-other\n}\nmenuentry 'also bad' {\n linux /boot/vmlinuz-other root=x\n initrd /boot/initrd.img-old-kernel\n}\n" > "$KERNEL_BOOT_DIR/grub/grub.cfg"
rc=0; verify_kernel_boot old-kernel || rc=$?
[[ "$rc" == 1 ]] || exit 99
''')

    def test_boot_check_accepts_separate_boot_partition_and_microcode(self):
        self.success(r'''
boot_fixture old-kernel
printf "submenu 'Advanced options' {\n menuentry 'Linux' {\n linux /vmlinuz-old-kernel root=x\n initrd /intel-ucode.img /initrd.img-old-kernel\n }\n}\n" > "$KERNEL_BOOT_DIR/grub/grub.cfg"
verify_kernel_boot old-kernel
''')

    def test_boot_check_rejects_invalid_grub_syntax(self):
        self.success(r'''
boot_fixture old-kernel
grub-script-check() { return 1; }
rc=0; verify_kernel_boot old-kernel || rc=$?
[[ "$rc" == 1 ]] || exit 99
''')

    def test_remove_does_not_run_dpkg_without_verified_fallback(self):
        self.success(r'''
mkdir -p "$KERNEL_STATE/$TAG"
printf linux-image-7.2.6-joeyblog-bbrv3 > "$KERNEL_STATE/$TAG/package"
printf 7.2.6-joeyblog-bbrv3 > "$KERNEL_STATE/$TAG/kernel"
boot_fixture old-kernel
rm "$KERNEL_BOOT_DIR/initrd.img-old-kernel"
update-grub() { :; }
run_step remove remove_kernel
[[ "$FAILED" == 1 && ! -f "$WORK/calls" ]] || exit 99
''')


if __name__ == '__main__':
    unittest.main()
