#!/usr/bin/env bash
SYSCTL_FILE=/etc/sysctl.d/90-shellready-bbr.conf
BBR_STATE=/var/lib/shellready/bbr
BBR_SYSCTL_DIRS=(/etc/sysctl.d /run/sysctl.d /usr/local/lib/sysctl.d /usr/lib/sysctl.d /lib/sysctl.d)
BBR_SYSCTL_MAIN=/etc/sysctl.conf

bbr_conflict_in_files() {
    # Only the exact congestion-control key is relevant; leave all other tuning alone.
    awk -F= '
        /^[[:space:]]*[#;]/ { next }
        NF >= 2 {
            key=$1; gsub(/[[:space:]]/, "", key); sub(/^-/, "", key)
            if (key != "net.ipv4.tcp_congestion_control" && key != "net/ipv4/tcp_congestion_control") next
            value=$2; sub(/[[:space:]]*[#;].*$/, "", value); gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            location=FILENAME ":" FNR
        }
        END { if (location != "" && value != "bbr") print location " = " value }
    ' "$@"
}

check_bbr_persistence() {
    local dir file name conflict LC_ALL=C
    local names=() ordered=()
    # sysctl.d sorts by basename; the first directory masks identical basenames.
    for dir in "${BBR_SYSCTL_DIRS[@]}"; do
        for file in "$dir"/*.conf; do
            [[ -e "$file" || -L "$file" ]] || continue
            name=${file##*/}
            [[ "$name" > "${SYSCTL_FILE##*/}" ]] || continue
            names+=("$name")
        done
    done
    if ((${#names[@]})); then
        while IFS= read -r name; do
            for dir in "${BBR_SYSCTL_DIRS[@]}"; do
                file="$dir/$name"
                [[ -e "$file" || -L "$file" ]] || continue
                [[ -r "$file" ]] || { fail "无法检查 BBR 持久配置：$file"; return 1; }
                ordered+=("$file")
                break
            done
        done < <(printf '%s\n' "${names[@]}" | LC_ALL=C sort -u)
        conflict=$(bbr_conflict_in_files "${ordered[@]}") || return 1
        if [[ -n "$conflict" ]]; then
            log "后续 sysctl 配置会覆盖 BBR：$conflict；保留原配置，跳过。"; return 2
        fi
    fi
    # procps sysctl --system also reads /etc/sysctl.conf last.
    if [[ -e "$BBR_SYSCTL_MAIN" || -L "$BBR_SYSCTL_MAIN" ]]; then
        [[ -r "$BBR_SYSCTL_MAIN" ]] || { fail "无法检查 BBR 持久配置：$BBR_SYSCTL_MAIN"; return 1; }
        conflict=$(bbr_conflict_in_files "$BBR_SYSCTL_MAIN") || return 1
        if [[ -n "$conflict" ]]; then
            log "sysctl --system 会覆盖 BBR：$conflict；保留原配置，跳过。"; return 2
        fi
    fi
}

install_bbr() {
    local available current
    available=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || true)
    if [[ " $available " != *' bbr '* ]]; then
        modprobe tcp_bbr 2>/dev/null || true
        available=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || true)
    fi
    if [[ " $available " != *' bbr '* ]]; then
        log '当前内核不提供 BBR，跳过；不安装新内核。'
        return 2
    fi
    check_bbr_persistence || return $?
    current=$(sysctl -n net.ipv4.tcp_congestion_control)
    if [[ -e "$SYSCTL_FILE" ]]; then
        [[ -f "$BBR_STATE/config.sha256" && ! -L "$SYSCTL_FILE" ]] || { fail 'BBR 配置已存在但缺少管理记录，保留原文件'; return 1; }
        verify_sha256 "$SYSCTL_FILE" "$(cat "$BBR_STATE/config.sha256")" || return 1
    else
        # Preserve an older interrupted transaction for explicit recovery.
        [[ ! -e "$BBR_STATE/original" ]] || { fail '存在未完成的 BBR 变更，请先用 uninstall --restore-bbr 恢复'; return 1; }
        mkdir -p "$BBR_STATE"
        chmod 700 "$BBR_STATE"
        printf '%s\n' "$current" > "$BBR_STATE/original"
        printf '# Managed by ShellReady\nnet.ipv4.tcp_congestion_control = bbr\n' > "$BBR_STATE/config"
        sha256sum "$BBR_STATE/config" | awk '{print $1}' > "$BBR_STATE/config.sha256"
        install -m 644 "$BBR_STATE/config" "$SYSCTL_FILE"
    fi
    if ! sysctl -w net.ipv4.tcp_congestion_control=bbr; then
        if restore_bbr; then
            fail 'BBR 应用失败，已恢复原设置。'
        else
            fail 'BBR 应用失败且未能自动恢复；请运行 uninstall --restore-bbr 检查恢复记录。'
        fi
        return 1
    fi
    [[ $(sysctl -n net.ipv4.tcp_congestion_control) == bbr ]] || { fail 'BBR 实际状态不符'; return 1; }
    log 'BBR 已启用并持久化；保留原网卡队列配置，不要求重启。'
}

restore_bbr() {
    local original current
    [[ -f "$BBR_STATE/original" ]] || { log '无 ShellReady BBR 恢复记录'; return 0; }
    if [[ -e "$SYSCTL_FILE" ]]; then
        [[ ! -L "$SYSCTL_FILE" ]] || { fail 'BBR 配置变成符号链接，拒绝恢复'; return 1; }
        verify_sha256 "$SYSCTL_FILE" "$(cat "$BBR_STATE/config.sha256")" || return 1
    fi
    original=$(cat "$BBR_STATE/original")
    current=$(sysctl -n net.ipv4.tcp_congestion_control)
    if [[ "$current" != bbr && "$current" != "$original" ]]; then
        fail '运行态算法已被其他操作修改，拒绝覆盖'; return 1
    fi
    [[ "$original" =~ ^[a-zA-Z0-9_]+$ ]] || { fail '原 BBR 状态记录无效'; return 1; }
    if [[ "$current" != "$original" ]]; then
        sysctl -w "net.ipv4.tcp_congestion_control=$original" || return 1
    fi
    rm -f "$SYSCTL_FILE" "$BBR_STATE/original" "$BBR_STATE/config" "$BBR_STATE/config.sha256" || return 1
    rmdir "$BBR_STATE" || return 1
    log "已恢复原 TCP 算法：$original"
}

status_bbr() {
    local algo version
    algo=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || true)
    version=$(modinfo -F version tcp_bbr 2>/dev/null || true)
    log "TCP 算法：${algo:-不可读取}；模块版本：${version:-未知（不据此推断 v3）}"
    if [[ -f "$SYSCTL_FILE" ]]; then check_bbr_persistence || return $?; fi
    if [[ -f "$SYSCTL_FILE" && -r "$BBR_STATE/config.sha256" ]]; then
        verify_sha256 "$SYSCTL_FILE" "$(cat "$BBR_STATE/config.sha256")" || return 1
        log 'BBR 持久配置存在；重启后的实际状态需在服务器验证。'
    fi
    [[ "$algo" == bbr ]] || return 2
}
