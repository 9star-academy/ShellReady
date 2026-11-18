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
KERNEL_MODULES_DIR="$WORK/modules"; KERNEL_GRUB_DEFAULTS_DIR="$WORK/grub-defaults"
ID=ubuntu; VERSION_ID=26.04
RESULTS=(); FAILED=0; SKIPPED=0
mkdir -p "$KERNEL_BOOT_DIR/grub" "$KERNEL_GRUB_DEFAULTS_DIR" "$KERNEL_MODULES_DIR/old-kernel" "$KERNEL_MODULES_DIR/7.2.6-joeyblog-bbrv3"
kernel_preflight() { :; }
apt-get() {
    printf 'apt-get %s\n' "$*" >> "$WORK/calls"
    case "$*" in *--no-remove*"$WORK/"*.deb*) touch "$WORK/dpkg-installed"; printf kernel > "$KERNEL_BOOT_DIR/vmlinuz-7.2.6-joeyblog-bbrv3" ;; esac
}
download() {
    if [[ "$1" == *api.github.com* ]]; then cp "$WORK/fixture.json" "$2"; else touch "$2"; fi
}
verify_sha256() { :; }
dpkg-deb() {
    if [[ "$1" == --contents ]]; then
        echo '-rw-r--r-- root/root 10485760 2026-11-18 00:00 ./boot/vmlinuz-7.2.6-joeyblog-bbrv3'
    elif [[ "$3" == Package ]]; then echo linux-image-7.2.6-joeyblog-bbrv3
    else echo amd64; fi
}
dpkg() { printf 'dpkg %s\n' "$*" >> "$WORK/calls"; echo amd64; }
dpkg-query() { if [[ -f "$WORK/dpkg-installed" ]]; then echo 'install ok installed'; else return 1; fi; }
uname() { echo old-kernel; }
grub-script-check() { :; }
df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted\nfixture 4000000 0 3000000 0%% /boot\n'; }
dracut() { printf 'dracut %s\n' "$*" >> "$WORK/calls"; printf initramfs > "$2"; }
boot_fixture() {
    printf kernel > "$KERNEL_BOOT_DIR/vmlinuz-$1"
    printf initramfs > "$KERNEL_BOOT_DIR/initrd.img-$1"
    printf "menuentry 'Linux' {\n linux /boot/vmlinuz-%s root=UUID=example\n initrd /boot/initrd.img-%s\n}\n" "$1" "$1" >> "$KERNEL_BOOT_DIR/grub/grub.cfg"
}
cloud_fixture() {
    printf kernel > "$KERNEL_BOOT_DIR/vmlinuz-old-kernel"
    ln -s initrd.img-old-kernel "$KERNEL_BOOT_DIR/initrd.img"
    printf "# GRUB_FORCE_PARTUUID is set, will attempt initrdless boot\nmenuentry 'Linux' {\n linux /vmlinuz-old-kernel root=PARTUUID=example\n}\n" > "$KERNEL_BOOT_DIR/grub/grub.cfg"
}
normal_grub() {
    : > "$KERNEL_BOOT_DIR/grub/grub.cfg"
    local image kernel
    for image in "$KERNEL_BOOT_DIR"/vmlinuz-*; do
        kernel=${image##*/vmlinuz-}
        printf "menuentry 'Linux' {\n linux /vmlinuz-%s root=UUID=example\n initrd /initrd.img-%s\n}\n" "$kernel" "$kernel" >> "$KERNEL_BOOT_DIR/grub/grub.cfg"
    done
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
: > "$KERNEL_BOOT_DIR/initrd.img-old-kernel"
rc=0; verify_kernel_files old-kernel || rc=$?
[[ "$rc" == 1 ]] || exit 99
rm "$KERNEL_BOOT_DIR/initrd.img-old-kernel"
mkdir "$KERNEL_BOOT_DIR/initrd.img-old-kernel"
rc=0; verify_kernel_files old-kernel || rc=$?
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

    def test_cloud_boot_prepares_existing_kernels_before_install_and_keeps_backup(self):
        self.success(r'''
cloud_fixture
printf kernel > "$KERNEL_BOOT_DIR/vmlinuz-older-kernel"
mkdir -p "$KERNEL_MODULES_DIR/older-kernel"
cp "$KERNEL_BOOT_DIR/grub/grub.cfg" "$WORK/original-grub"
kernel_preflight() { kernel_initrdless_candidate; KERNEL_PREPARE_INITRDLESS=1; kernel_check_boot_space; }
update-grub() {
    [[ -s "$KERNEL_BOOT_DIR/initrd.img-old-kernel" && -s "$KERNEL_BOOT_DIR/initrd.img-older-kernel" ]] || return 99
    [[ -s "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg" ]] || return 99
    normal_grub
}
df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted\nfixture 1012736 55296 888832 6%% /boot\n'; }
run_step cloud install_kernel
[[ "$FAILED" == 0 && "$SKIPPED" == 1 && -f "$KERNEL_STATE/$TAG/installed" ]] || exit 99
verify_kernel_boot old-kernel
verify_kernel_boot 7.2.6-joeyblog-bbrv3
cmp "$WORK/original-grub" "$KERNEL_STATE"/boot-preparation.*/grub.cfg || exit 99
[[ -L "$KERNEL_BOOT_DIR/initrd.img" && -s "$KERNEL_BOOT_DIR/initrd.img" ]] || exit 99
''')

    def test_cloud_generation_failure_restores_grub_without_installing_target(self):
        self.success(r'''
cloud_fixture
cp "$KERNEL_BOOT_DIR/grub/grub.cfg" "$WORK/original-grub"
kernel_preflight() { kernel_initrdless_candidate; KERNEL_PREPARE_INITRDLESS=1; }
dracut() { printf partial > "$2"; return 1; }
update-grub() { echo unexpected-grub >> "$WORK/calls"; return 99; }
run_step cloud install_kernel
[[ "$FAILED" == 1 && ! -f "$WORK/dpkg-installed" && ! -e "$KERNEL_STATE/$TAG/installed" ]] || exit 99
[[ ! -e "$KERNEL_BOOT_DIR/initrd.img-old-kernel" && ! -e "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg" ]] || exit 99
cmp "$WORK/original-grub" "$KERNEL_BOOT_DIR/grub/grub.cfg" || exit 99
[[ -z $(find "$KERNEL_BOOT_DIR" -name '.shellready-*' -print) ]] || exit 99
''')

    def test_cloud_grub_failure_rolls_back_override_and_configuration(self):
        self.success(r'''
cloud_fixture
cp "$KERNEL_BOOT_DIR/grub/grub.cfg" "$WORK/original-grub"
kernel_preflight() { kernel_initrdless_candidate; KERNEL_PREPARE_INITRDLESS=1; }
update-grub() { printf broken > "$KERNEL_BOOT_DIR/grub/grub.cfg"; return 1; }
run_step cloud install_kernel
[[ "$FAILED" == 1 && ! -f "$WORK/dpkg-installed" && -s "$KERNEL_BOOT_DIR/initrd.img-old-kernel" ]] || exit 99
[[ ! -e "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg" ]] || exit 99
cmp "$WORK/original-grub" "$KERNEL_BOOT_DIR/grub/grub.cfg" || exit 99
''')

    def test_cloud_boot_never_overwrites_an_existing_override(self):
        self.success(r'''
cloud_fixture
printf custom > "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg"
update-grub() { echo unexpected > "$WORK/calls"; }
rc=0; kernel_prepare_initramfs_boot || rc=$?
[[ "$rc" == 1 && ! -f "$WORK/calls" && ! -d "$KERNEL_STATE" ]] || exit 99
[[ $(cat "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg") == custom ]] || exit 99
''')

    def test_an_override_ignored_by_grub_is_not_reported_as_ready(self):
        self.success(r'''
cloud_fixture
cp "$KERNEL_BOOT_DIR/grub/grub.cfg" "$WORK/original-grub"
update-grub() { :; }
rc=0; kernel_prepare_initramfs_boot || rc=$?
[[ "$rc" == 1 && ! -e "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg" ]] || exit 99
cmp "$WORK/original-grub" "$KERNEL_BOOT_DIR/grub/grub.cfg" || exit 99
''')

    def test_missing_initramfs_without_cloud_mode_is_not_auto_prepared(self):
        self.success(r'''
boot_fixture old-kernel
rm "$KERNEL_BOOT_DIR/initrd.img-old-kernel"
if kernel_initrdless_candidate; then exit 99; fi
rc=0; verify_or_repair_kernel_boot || rc=$?
[[ "$rc" == 1 && ! -f "$WORK/calls" ]] || exit 99
''')

    def test_existing_cloud_initramfs_still_requires_normal_boot_mode(self):
        self.success(r'''
cloud_fixture
printf initramfs > "$KERNEL_BOOT_DIR/initrd.img-old-kernel"
kernel_initrdless_candidate
rc=0; verify_kernel_boot old-kernel || rc=$?
[[ "$rc" == 1 ]] || exit 99
''')

    def test_boot_budget_accepts_868_mib_but_checks_large_packages_and_low_space(self):
        self.success(r'''
df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted\nfixture 1012736 55296 888832 6%% /boot\n'; }
kernel_package_boot_budget fixture 7.2.6-joeyblog-bbrv3
dpkg-deb() { echo '-rw-r--r-- root/root 734003200 2026-11-18 00:00 ./boot/vmlinuz-7.2.6-joeyblog-bbrv3'; }
rc=0; kernel_package_boot_budget fixture 7.2.6-joeyblog-bbrv3 || rc=$?
[[ "$rc" == 1 ]] || exit 99
df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted\nfixture 1012736 0 523264 50%% /boot\n'; }
rc=0; kernel_check_boot_space || rc=$?
[[ "$rc" == 1 ]] || exit 99
''')

    def test_failed_target_initramfs_can_resume_without_reinstalling_package(self):
        self.success(r'''
boot_fixture old-kernel
dracut() { printf partial > "$2"; return 1; }
update-grub() { normal_grub; }
run_step first install_kernel
[[ "$FAILED" == 1 && -f "$WORK/dpkg-installed" && ! -e "$KERNEL_STATE/$TAG/installed" ]] || exit 99
dracut() { printf initramfs > "$2"; }
FAILED=0; SKIPPED=0
run_step retry install_kernel
[[ "$FAILED" == 0 && "$SKIPPED" == 1 && -f "$KERNEL_STATE/$TAG/installed" ]] || exit 99
[[ $(grep -c 'apt-get install -y --no-remove' "$WORK/calls") == 1 ]] || exit 99
''')

    def test_classic_initramfs_generator_remains_supported(self):
        self.success(r'''
command() {
    if [[ "$*" == '-v dracut' ]]; then return 1; fi
    builtin command "$@"
}
mkinitramfs() { printf classic > "$2"; }
kernel_ensure_initramfs_tool
kernel_generate_initramfs old-kernel
[[ $(cat "$KERNEL_BOOT_DIR/initrd.img-old-kernel") == classic && ! -f "$WORK/calls" ]] || exit 99
''')

    def test_generator_install_failure_restores_grub_touched_by_package_hooks(self):
        self.success(r'''
cloud_fixture
cp "$KERNEL_BOOT_DIR/grub/grub.cfg" "$WORK/original-grub"
command() {
    case "$*" in '-v dracut'|'-v mkinitramfs') return 1 ;; *) builtin command "$@" ;; esac
}
apt-get() { printf modified > "$KERNEL_BOOT_DIR/grub/grub.cfg"; return 1; }
update-grub() { echo unexpected > "$WORK/calls"; }
rc=0; kernel_prepare_initramfs_boot || rc=$?
[[ "$rc" == 1 && ! -f "$WORK/calls" && ! -e "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg" ]] || exit 99
cmp "$WORK/original-grub" "$KERNEL_BOOT_DIR/grub/grub.cfg" || exit 99
''')

    def test_invalid_record_prevents_cloud_boot_changes(self):
        self.success(r'''
cloud_fixture
kernel_preflight() { kernel_initrdless_candidate; KERNEL_PREPARE_INITRDLESS=1; }
mkdir -p "$KERNEL_STATE/$TAG"
printf wrong > "$KERNEL_STATE/$TAG/package"
update-grub() { echo unexpected-grub >> "$WORK/calls"; }
run_step invalid install_kernel
[[ "$FAILED" == 1 && ! -f "$WORK/dpkg-installed" && ! -e "$KERNEL_BOOT_DIR/initrd.img-old-kernel" ]] || exit 99
[[ ! -e "$KERNEL_GRUB_DEFAULTS_DIR/zz-shellready-initramfs.cfg" ]] || exit 99
''')


if __name__ == '__main__':
    unittest.main()
