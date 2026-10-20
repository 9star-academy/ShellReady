#!/usr/bin/env bash
QDISC_FILE=/etc/sysctl.d/90-shellready-fq.conf
QDISC_STATE=/var/lib/shellready/qdisc

qdisc_dependencies() {
    local binary
    for binary in ip tc jq; do
        command -v "$binary" >/dev/null 2>&1 || { fail "缺少 ${binary}；FQ 操作需要 iproute2 和 jq，请先安装。"; return 1; }
    done
}

qdisc_interfaces() {
    local routes
    routes=$(ip -o route show default) || return 1
    routes+=$'\n'
    routes+=$(ip -o -6 route show default) || return 1
    awk '{for (i=1; i<NF; i++) if ($i=="dev") print $(i+1)}' <<< "$routes" | LC_ALL=C sort -u
}

qdisc_snapshot() {
    tc -j qdisc show dev "$1" | jq -ceS 'sort_by(.parent // "", .kind) | map(del(.refcnt))'
}

qdisc_same() {
    [[ $(jq -cS 'map(del(.refcnt))' "$1") == "$(jq -cS 'map(del(.refcnt))' "$2")" ]]
}

qdisc_original_same() {
    # Zero handles are kernel defaults. Restoring their options can allocate a
    # fresh handle; no user class/filter references to those zero handles exist.
    [[ $(jq -cS 'map(del(.refcnt, .handle))' "$1") == "$(jq -cS 'map(del(.refcnt, .handle))' "$2")" ]]
}

check_qdisc_persistence() {
    # Dynamically scoped inputs consumed by the shared sysctl checker.
    # shellcheck disable=SC2034
    local SYSCTL_FILE=$QDISC_FILE BBR_SYSCTL_KEY=net.core.default_qdisc BBR_SYSCTL_VALUE=fq
    check_bbr_persistence
}

qdisc_supported_snapshot() {
    jq -e '
        def leaf:
            .handle == "0:" and
            (if .kind == "fq" then true
             elif .kind == "fq_codel" then
                 (.options | type == "object") and
                 (.options | keys - ["limit","flows","quantum","target","interval","memory_limit","ecn","drop_batch","ce_threshold"] | length == 0) and
                 (.options | to_entries | all(if .key == "ecn" then .value | type == "boolean" else .value | type == "number" and . >= 0 end))
             elif .kind == "pfifo_fast" then
                 .options.bands == 3 and .options.priomap == [1,2,2,2,1,2,0,0,1,1,1,1,1,1,1,1]
             else false end);
        type == "array" and length > 0 and
        ([.[] | select(.root == true)] | length == 1) and
        (if any(.[]; .kind == "mq" and .root == true and .handle == "0:") then
            length > 1 and all(.[]; .kind == "mq" or
                ((.parent // "" | test("^[0-9a-f]*:[0-9a-f]+$")) and leaf))
         else length == 1 and (.[0] | leaf) end)
    ' "$1" >/dev/null
}

# Restore only the two recognized baseline kinds. All arguments are separate
# array elements from numeric/boolean JSON, never an evaluated command string.
qdisc_restore_leaf() {
    local iface=$1 row=$2 parent kind key value
    local args=(qdisc replace dev "$iface")
    parent=$(jq -r '.parent // ""' <<< "$row")
    if [[ -n "$parent" ]]; then args+=(parent "$parent"); else args+=(root); fi
    kind=$(jq -r '.kind' <<< "$row")
    args+=(handle 0: "$kind")
    if [[ "$kind" == fq_codel ]]; then
        # tc JSON omits ecn when it is disabled; fq_codel itself defaults to on.
        if ! jq -e '.options.ecn == true' <<< "$row" >/dev/null; then args+=(noecn); fi
        while IFS=$'\t' read -r key value; do
            case "$key" in
                ecn) if [[ "$value" == true ]]; then args+=(ecn); else args+=(noecn); fi ;;
                target|interval|ce_threshold) args+=("$key" "${value}us") ;;
                *) args+=("$key" "$value") ;;
            esac
        done < <(jq -r '.options | to_entries[] | [.key, (.value|tostring)] | @tsv' <<< "$row")
    fi
    tc "${args[@]}"
}

qdisc_restore_interfaces() {
    local directory iface current row filters failed=0
    # Precheck all interfaces before modifying any of them.
    for directory in "$QDISC_STATE/interfaces/"*; do
        [[ -d "$directory" ]] || continue
        iface=${directory##*/}
        filters=$(tc filter show dev "$iface") || return 1
        [[ -z "$filters" ]] || { fail "${iface} 已增加 TC 过滤规则，保留恢复记录。"; return 1; }
        current=$(qdisc_snapshot "$iface") || return 1
        printf '%s\n' "$current" > "$directory/check.json"
        if ! qdisc_original_same "$directory/check.json" "$directory/before.json" &&
            ! qdisc_original_same "$directory/check.json" "$directory/after.json"; then
            fail "${iface} 队列已被其他操作修改，保留恢复记录。"; return 1
        fi
    done
    for directory in "$QDISC_STATE/interfaces/"*; do
        [[ -d "$directory" ]] || continue
        iface=${directory##*/}
        if qdisc_original_same "$directory/check.json" "$directory/before.json"; then continue; fi
        while IFS= read -r row; do
            qdisc_restore_leaf "$iface" "$row" || { failed=1; break; }
            qdisc_snapshot "$iface" > "$directory/after.new" || return 1
            mv "$directory/after.new" "$directory/after.json" || return 1
        done < <(jq -c '.[] | select(.kind == "fq_codel" or .kind == "pfifo_fast")' "$directory/before.json")
        [[ "$failed" == 0 ]] || return 1
        qdisc_original_same "$directory/after.json" "$directory/before.json" || {
            fail "${iface} 原队列尚未完全恢复，保留记录。"; return 1;
        }
    done
}

restore_qdisc() {
    local original current
    [[ -d "$QDISC_STATE" ]] || { log '无 ShellReady 队列恢复记录。'; return 0; }
    qdisc_dependencies || return 1
    [[ -f "$QDISC_STATE/original" ]] || { fail '队列恢复记录不完整，请检查后再操作。'; return 1; }
    if [[ -e "$QDISC_FILE" || -L "$QDISC_FILE" ]]; then
        [[ ! -L "$QDISC_FILE" && -f "$QDISC_STATE/config.sha256" ]] || { fail '队列配置归属不符，保留原文件。'; return 1; }
        verify_sha256 "$QDISC_FILE" "$(cat "$QDISC_STATE/config.sha256")" || return 1
    fi
    original=$(cat "$QDISC_STATE/original")
    [[ "$original" =~ ^[a-zA-Z0-9_]+$ ]] || return 1
    current=$(sysctl -n net.core.default_qdisc) || return 1
    [[ "$current" == fq || "$current" == "$original" ]] || { fail '默认队列已被其他操作修改，拒绝覆盖。'; return 1; }
    qdisc_restore_interfaces || return 1
    if [[ "$current" != "$original" ]]; then sysctl -w "net.core.default_qdisc=$original" || return 1; fi
    [[ $(sysctl -n net.core.default_qdisc) == "$original" ]] || return 1
    rm -f "$QDISC_FILE" || return 1
    rm -rf -- "$QDISC_STATE" || return 1
    log "已恢复原默认队列及本项目修改的出口队列：$original"
}

apply_fq_interfaces() {
    local directory iface row parent
    for directory in "$QDISC_STATE/interfaces/"*; do
        [[ -d "$directory" ]] || continue
        iface=${directory##*/}
        qdisc_snapshot "$iface" > "$directory/check.json" || return 1
        qdisc_same "$directory/check.json" "$directory/before.json" || {
            fail "${iface} 队列在检查后发生变化，停止操作。"; return 1;
        }
        while IFS= read -r row; do
            parent=$(jq -r '.parent // ""' <<< "$row")
            if [[ -n "$parent" ]]; then
                tc qdisc replace dev "$iface" parent "$parent" fq || return 1
            else
                tc qdisc replace dev "$iface" root fq || return 1
            fi
            qdisc_snapshot "$iface" > "$directory/after.new" || return 1
            mv "$directory/after.new" "$directory/after.json" || return 1
        done < <(jq -c '.[] | select(.kind == "fq_codel" or .kind == "pfifo_fast")' "$directory/before.json")
        jq -e 'all(.[]; .kind == "mq" or .kind == "fq")' "$directory/after.json" >/dev/null || return 1
    done
}

install_bbr_fq() {
    local interfaces iface snapshot filters original directory
    qdisc_dependencies || return 1
    check_bbr_persistence || return $?
    check_qdisc_persistence || return $?
    if [[ -d "$QDISC_STATE" || -e "$QDISC_FILE" || -L "$QDISC_FILE" ]]; then
        [[ -f "$QDISC_STATE/installed" && -f "$QDISC_STATE/config.sha256" && ! -L "$QDISC_FILE" ]] || {
            fail '已有队列配置或未完成的变更，请先用 bbr-restore --yes 恢复。'; return 1;
        }
        verify_sha256 "$QDISC_FILE" "$(cat "$QDISC_STATE/config.sha256")" || return 1
        [[ $(sysctl -n net.core.default_qdisc) == fq ]] || { fail '默认队列已改变，请先检查或恢复。'; return 1; }
        for directory in "$QDISC_STATE/interfaces/"*; do
            iface=${directory##*/}
            snapshot=$(qdisc_snapshot "$iface") || return 1
            jq -e 'all(.[]; .kind == "mq" or .kind == "fq")' <<< "$snapshot" >/dev/null || {
                fail "${iface} 当前队列不再是 FQ，请先检查或恢复。"; return 1;
            }
        done
        install_bbr || return $?
        log 'BBR + FQ 已配置；保留已有恢复记录。'; return 0
    fi
    interfaces=$(qdisc_interfaces) || return 1
    [[ -n "$interfaces" ]] || { log '没有默认路由出口，跳过 FQ。'; return 2; }
    mkdir -p "$WORK/qdisc-plan" || return 1
    while IFS= read -r iface; do
        [[ "$iface" =~ ^[a-zA-Z0-9_.:-]+$ ]] || { fail '无法安全识别出口网卡名'; return 1; }
        snapshot=$(qdisc_snapshot "$iface") || return 1
        printf '%s\n' "$snapshot" > "$WORK/qdisc-plan/$iface.json"
        if ! qdisc_supported_snapshot "$WORK/qdisc-plan/$iface.json"; then
            log "${iface} 存在自定义或暂不支持的队列，保留现状并跳过 FQ。"; return 2
        fi
        filters=$(tc filter show dev "$iface") || return 1
        [[ -z "$filters" ]] || { log "${iface} 存在 TC 过滤规则，保留现状并跳过。"; return 2; }
    done <<< "$interfaces"
    original=$(sysctl -n net.core.default_qdisc) || return 1
    [[ "$original" =~ ^[a-zA-Z0-9_]+$ ]] || return 1
    # FQ can be built into the kernel; setting the sysctl below checks support.
    modprobe sch_fq 2>/dev/null || true
    mkdir -p "$QDISC_STATE/interfaces" || return 1
    chmod 700 "$QDISC_STATE" || return 1
    printf '%s\n' "$original" > "$QDISC_STATE/original"
    while IFS= read -r iface; do
        directory="$QDISC_STATE/interfaces/$iface"
        mkdir -p "$directory" || return 1
        cp "$WORK/qdisc-plan/$iface.json" "$directory/before.json" || return 1
        cp "$directory/before.json" "$directory/after.json" || return 1
    done <<< "$interfaces"
    printf '# Managed by ShellReady\nnet.core.default_qdisc = fq\n' > "$QDISC_STATE/config"
    sha256sum "$QDISC_STATE/config" | awk '{print $1}' > "$QDISC_STATE/config.sha256"
    if ! sysctl -w net.core.default_qdisc=fq || ! apply_fq_interfaces ||
        ! install -m 644 "$QDISC_STATE/config" "$QDISC_FILE" || ! install_bbr; then
        if restore_qdisc; then fail 'BBR + FQ 应用失败，队列变更已恢复。'
        else fail 'BBR + FQ 应用未完成，保留记录；请运行 bbr-restore --yes 检查恢复。'; fi
        return 1
    fi
    [[ $(sysctl -n net.core.default_qdisc) == fq ]] || return 1
    touch "$QDISC_STATE/installed"
    log 'BBR + FQ 已应用；保留 mq 根队列，未修改 TCP 缓冲区或带宽限制。'
    log '默认队列已持久化；重启后的网卡实际队列需再次检查。'
}

status_qdisc() {
    local interfaces iface
    log "默认队列：$(sysctl -n net.core.default_qdisc 2>/dev/null || printf '不可读取')"
    if ! command -v ip >/dev/null 2>&1 || ! command -v tc >/dev/null 2>&1; then
        log '缺少 ip/tc，无法读取实际出口队列。'; return 2
    fi
    interfaces=$(qdisc_interfaces) || return 1
    [[ -n "$interfaces" ]] || { log '没有默认路由出口。'; return 2; }
    while IFS= read -r iface; do
        log "实际出口：$iface"
        tc qdisc show dev "$iface" || return 1
    done <<< "$interfaces"
    if [[ -d "$QDISC_STATE" ]]; then
        if [[ ! -x "$QDISC_STATE" ]]; then
            log '管理记录需要 root 权限核验；上方显示的是实际网卡状态。'
        elif [[ ! -f "$QDISC_STATE/installed" ]]; then
            log '队列变更未完成，请检查并通过 bbr-restore --yes 恢复。'; return 2
        else
            verify_sha256 "$QDISC_FILE" "$(cat "$QDISC_STATE/config.sha256")" || return 1
            check_qdisc_persistence || return $?
        fi
    fi
}
