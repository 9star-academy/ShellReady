#!/usr/bin/env bash
KERNEL_STATE=/var/lib/shellready/kernels

validate_kernel_tag() {
    local expected
    case "$ARCH" in x86_64) expected=x86_64 ;; aarch64) expected=arm64 ;; *) return 1 ;; esac
    [[ "$TAG" =~ ^${expected}-[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
        fail "只接受当前架构的标准版 tag（如 ${expected}-X.Y.Z），不接受 latest 或 Max"; return 1;
    }
}

kernel_preflight() {
    validate_kernel_tag
    # shellcheck disable=SC1091
    source /etc/os-release
    case "$ID:${VERSION_ID:-}" in ubuntu:24.04|debian:12|debian:13) ;; *) fail '可选内核仅允许 Ubuntu 24.04、Debian 12/13'; return 1 ;; esac
    command -v systemd-detect-virt >/dev/null 2>&1 || { fail '缺少 systemd-detect-virt，无法验证是否为独立内核环境'; return 1; }
    if systemd-detect-virt --container --quiet; then
        fail '容器共享宿主内核，不允许在容器安装内核'; return 1
    fi
    command -v update-grub >/dev/null 2>&1 || { fail '未检测到 update-grub，首版不支持此引导方式'; return 1; }
    [[ -f "/boot/vmlinuz-$(uname -r)" ]] || { fail '无法确认当前内核的回退启动文件'; return 1; }
    local free_kb
    free_kb=$(df -Pk /boot | awk 'END {print $4}')
    if [[ ! "$free_kb" =~ ^[0-9]+$ ]] || ((free_kb < 1048576)); then
        fail '/boot 所在分区至少需要 1 GiB 可用空间'; return 1
    fi
    if [[ -d /sys/firmware/efi ]]; then
        command -v mokutil >/dev/null 2>&1 || { fail 'UEFI 环境需要 mokutil 核验 Secure Boot 状态'; return 1; }
        LC_ALL=C mokutil --sb-state | grep -q 'SecureBoot disabled' || { fail '未确认 Secure Boot 关闭，不安装第三方内核'; return 1; }
    fi
}

install_kernel() {
    kernel_preflight
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates jq kmod
    local metadata="$WORK/release.json" row name url digest deb pkg package_arch kernel record
    download "https://api.github.com/repos/byJoey/Actions-bbr-v3/releases/tags/$TAG" "$metadata"
    jq -e --arg tag "$TAG" '.tag_name == $tag and .draft == false and .prerelease == false' "$metadata" >/dev/null
    row=$(jq -r '[.assets[] | select(.name | test("^linux-image-[0-9].*joeyblog.*\\.deb$")) | select(.name | test("dbg|dbgsym|max") | not)] | if length == 1 then .[0] | [.name,.browser_download_url,.digest] | @tsv else error("expected one standard image package") end' "$metadata")
    IFS=$'\t' read -r name url digest <<< "$row"
    [[ "$name" != */* && "$url" == "https://github.com/byJoey/Actions-bbr-v3/releases/download/$TAG/"* ]] || { fail '内核产物路径不符'; return 1; }
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { fail '发行包没有 SHA-256 digest，拒绝安装'; return 1; }
    deb="$WORK/$name"
    download "$url" "$deb"
    verify_sha256 "$deb" "${digest#sha256:}"
    pkg=$(dpkg-deb -f "$deb" Package)
    package_arch=$(dpkg-deb -f "$deb" Architecture)
    [[ "$pkg" =~ ^linux-image-[0-9]+\.[0-9]+\.[0-9]+-joeyblog-bbrv3$ ]] || { fail '内核包名称不符合标准版要求'; return 1; }
    [[ "$package_arch" == "$(dpkg --print-architecture)" ]] || { fail '内核包架构不符'; return 1; }
    kernel=${pkg#linux-image-}
    [[ "$kernel" == "${TAG#*-}-joeyblog-bbrv3" ]] || { fail '包版本与指定 tag 不符'; return 1; }
    record="$KERNEL_STATE/$TAG"
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -qx 'install ok installed'; then
        log "内核包已存在：${pkg}；不接管此前由其他方式安装的内核。"
        log "当前运行：$(uname -r)；目标：$kernel"
        [[ "$(uname -r)" == "$kernel" ]] || return 2
        return 0
    fi
    mkdir -p "$record"
    chmod 755 "$KERNEL_STATE" "$record"
    printf '%s\n' "$pkg" > "$record/package"
    printf '%s\n' "$kernel" > "$record/kernel"
    printf '%s\n' "${digest#sha256:}" > "$record/sha256"
    printf '%s\n' "$(uname -r)" > "$record/previous-kernel"
    # --no-remove prevents apt resolving dependencies by removing other packages.
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-remove "$deb"
    update-grub
    [[ -f "/boot/vmlinuz-$kernel" ]] || { fail '安装后未找到内核启动文件，请勿重启'; return 1; }
    [[ -f "/boot/initrd.img-$kernel" ]] || { fail '安装后未找到 initramfs，请勿重启'; return 1; }
    touch "$record/installed"
    log "已安装，待重启验证：${kernel}。旧内核已保留。"
    log '请在可接受业务中断时自行重启整台服务器；重新连接后运行 status。'
    return 2
}

status_kernel() {
    local record kernel pending=0 version
    log "当前运行内核：$(uname -r)"
    [[ -d "$KERNEL_STATE" ]] || return 0
    for record in "$KERNEL_STATE"/*; do
        [[ -f "$record/kernel" ]] || continue
        kernel=$(cat "$record/kernel")
        if [[ ! -e "$record/installed" ]]; then
            log "${kernel}：安装未完成，请检查包和引导配置，不要直接重启。"; pending=1
        elif [[ $(uname -r) == "$kernel" ]]; then
            version=$(cat /sys/module/tcp_bbr/version 2>/dev/null || true)
            if [[ "$version" == 3 && $(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null) == bbr ]]; then
                log "${kernel}：正在运行，已加载 BBRv3 且算法为 bbr。"
            else
                log "${kernel}：正在运行，但尚未确认已加载并启用 BBRv3。"; pending=1
            fi
        else
            log "${kernel}：已安装，当前未运行（待重启或引导选择不同）。"; pending=1
        fi
    done
    [[ "$pending" == 0 ]] || return 2
}

remove_kernel() {
    validate_kernel_tag
    local record="$KERNEL_STATE/$TAG" pkg kernel
    [[ -f "$record/package" && -f "$record/kernel" ]] || { fail '未找到此版本的 ShellReady 安装记录'; return 1; }
    pkg=$(cat "$record/package")
    kernel=$(cat "$record/kernel")
    [[ "$pkg" =~ ^linux-image-[0-9]+\.[0-9]+\.[0-9]+-joeyblog-bbrv3$ && "$kernel" == "${pkg#linux-image-}" ]] || return 1
    [[ "$kernel" != "$(uname -r)" ]] || { fail '不能卸载正在运行的内核；请先启动旧内核'; return 1; }
    [[ -f "/boot/vmlinuz-$(uname -r)" ]] || { fail '无法确认当前回退内核启动文件'; return 1; }
    command -v update-grub >/dev/null 2>&1 || return 1
    dpkg --remove "$pkg"
    update-grub
    rm -rf -- "$record"
    log "已移除非运行内核：${kernel}；未执行重启。"
}
