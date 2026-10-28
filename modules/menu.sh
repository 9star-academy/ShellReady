#!/usr/bin/env bash
# B2 colors are scoped to printed rows; never change the terminal's theme/state.
menu_style() {
    MENU_RESET=''; MENU_BG=''; MENU_TEXT_COLOR=''; MENU_ACCENT=''; MENU_MUTED=''
    MENU_GREEN=''; MENU_WARN=''; MENU_CREAM=''; MENU_SELECTED_BG=''
    if [[ -t 1 && ${TERM:-dumb} != dumb && -z ${NO_COLOR:-} ]]; then
        MENU_RESET=$'\033[0m'
        case "${COLORTERM:-}:${TERM:-}" in
            truecolor:*|24bit:*|*:*direct*)
                MENU_BG=$'\033[48;2;36;31;25m'; MENU_TEXT_COLOR=$'\033[38;2;239;228;208m'
                MENU_ACCENT=$'\033[38;2;241;198;94m'; MENU_MUTED=$'\033[38;2;183;168;142m'
                MENU_GREEN=$'\033[38;2;180;196;145m'; MENU_WARN=$'\033[38;2;221;154;127m'
                MENU_CREAM=$'\033[38;2;255;240;207m'; MENU_SELECTED_BG=$'\033[48;2;81;68;53m' ;;
            *:*-256color*)
                MENU_BG=$'\033[48;5;235m'; MENU_TEXT_COLOR=$'\033[38;5;223m'
                MENU_ACCENT=$'\033[38;5;221m'; MENU_MUTED=$'\033[38;5;144m'
                MENU_GREEN=$'\033[38;5;150m'; MENU_WARN=$'\033[38;5;180m'
                MENU_CREAM=$'\033[38;5;230m'; MENU_SELECTED_BG=$'\033[48;5;238m' ;;
            *)
                MENU_TEXT_COLOR=$'\033[37m'; MENU_ACCENT=$'\033[33m'; MENU_MUTED=$'\033[37m'
                MENU_GREEN=$'\033[32m'; MENU_WARN=$'\033[33m'
                MENU_CREAM=$'\033[1;37m'; MENU_SELECTED_BG=$'\033[100m' ;;
        esac
    fi
}

menu_dimensions() {
    local minimum_rows=${1:-24} size rows='' columns=''
    if [[ -t 0 && -t 1 ]]; then
        size=$(stty size 2>/dev/null || true)
        read -r rows columns <<< "$size" || true
    fi
    [[ "$rows" =~ ^[1-9][0-9]{0,3}$ ]] || rows=24
    [[ "$columns" =~ ^[1-9][0-9]{0,3}$ ]] || columns=80
    MENU_ROWS=$rows; MENU_COLUMNS=$columns
    MENU_WIDTH=$((columns - 1))
    if ((MENU_WIDTH > 78)); then MENU_WIDTH=78; fi
    MENU_KEYS=0; MENU_READ_KEYS=0
    if [[ -t 0 && -t 1 && ${TERM:-dumb} != dumb && -z ${NO_COLOR:-} ]]; then
        MENU_READ_KEYS=1
        if ((rows >= minimum_rows && columns >= 64)); then MENU_KEYS=1; fi
    fi
}

# Fit the Chinese/ASCII labels to display cells, not UTF-8 byte counts.
# Strip controls from OS metadata before writing it into a terminal.
menu_fit() {
    # Decode UTF-8 bytes explicitly: Bash 3 printf returns a signed first byte,
    # and servers with LC_ALL=C otherwise slice a Chinese glyph into bytes.
    local LC_ALL=C
    local value=$1 limit=$2 char code width index bytes offset byte
    MENU_TEXT=''; MENU_TEXT_WIDTH=0
    for ((index=0; index<${#value}; index++)); do
        printf -v code '%d' "'${value:index:1}"
        code=$((code & 255)); bytes=1
        if ((code >= 240)); then bytes=4; code=$((code & 7))
        elif ((code >= 224)); then bytes=3; code=$((code & 15))
        elif ((code >= 192)); then bytes=2; code=$((code & 31)); fi
        char=${value:index:bytes}
        for ((offset=1; offset<bytes; offset++)); do
            printf -v byte '%d' "'${value:index+offset:1}"
            code=$(((code << 6) | (byte & 63)))
        done
        index=$((index + bytes - 1))
        ((code >= 32 && (code < 127 || code > 159))) || continue
        width=1
        if (( (code >= 0x2e80 && code <= 0xa4cf) || (code >= 0xac00 && code <= 0xd7af) ||
              (code >= 0xf900 && code <= 0xfaff) || (code >= 0xff01 && code <= 0xff60) ||
              (code >= 0x20000 && code <= 0x3ffff) )); then width=2; fi
        ((MENU_TEXT_WIDTH + width <= limit)) || break
        MENU_TEXT+=$char; MENU_TEXT_WIDTH=$((MENU_TEXT_WIDTH + width))
    done
}

menu_line() {
    local color=${2:-$MENU_TEXT_COLOR}
    menu_fit "$1" "$MENU_WIDTH"
    printf '%b%s%*s%b\n' "$MENU_BG$color" "$MENU_TEXT" "$((MENU_WIDTH - MENU_TEXT_WIDTH))" '' "$MENU_RESET"
    MENU_LINES=$((MENU_LINES + 1))
}

menu_separator() {
    local line
    printf -v line '%*s' "$MENU_WIDTH" ''
    menu_line "${line// /─}" "$MENU_ACCENT"
}

menu_section() {
    local line
    menu_fit "$1" "$MENU_WIDTH"
    printf -v line '%*s' "$((MENU_WIDTH - MENU_TEXT_WIDTH))" ''
    menu_line "$1 ${line// /─}" "$MENU_ACCENT"
}

menu_item() {
    local number=$1 label=$2 status=${3:-} label_color=${4:-$MENU_TEXT_COLOR}
    local item_prefix status_width label_width padding number_color=$MENU_ACCENT status_color=$MENU_ACCENT bg=$MENU_BG
    case "$status" in
        '[已启用]'|'[推荐]') status_color=$MENU_GREEN ;;
        '[未安装]'|'[只读]') status_color=$MENU_MUTED ;;
    esac
    printf -v item_prefix '  %2s. ' "$number"
    if [[ "$MENU_KEYS" == 1 && "$MENU_SELECTED" == "$number" ]]; then
        printf -v item_prefix '> %2s. ' "$number"
        bg=$MENU_SELECTED_BG; number_color=$MENU_CREAM; label_color=$MENU_CREAM; status_color=$MENU_CREAM
    fi
    menu_fit "$status" "$((MENU_WIDTH / 3))"; status=$MENU_TEXT; status_width=$MENU_TEXT_WIDTH
    label_width=$((MENU_WIDTH - 6 - status_width))
    if [[ -n "$status" ]]; then label_width=$((label_width - 1)); fi
    # Very narrow terminals use the numeric fallback and may wrap naturally.
    if ((label_width < 1)); then label_width=1; fi
    menu_fit "$label" "$label_width"; label=$MENU_TEXT
    padding=$((MENU_WIDTH - 6 - MENU_TEXT_WIDTH - status_width))
    if ((padding < 0)); then padding=0; fi
    printf '%b%s%b%s%*s%b%s%b\n' "$bg$number_color" "$item_prefix" "$label_color" "$label" \
        "$padding" '' "$status_color" "$status" "$MENU_RESET"
    MENU_LINES=$((MENU_LINES + 1))
}

menu_component_badge() {
    local tool=$1 binary
    if ! component_installed "$tool" 2>/dev/null; then
        if [[ -n $(component_dirs "$tool" 2>/dev/null) ]]; then printf '[待修复]'; else printf '[未安装]'; fi
    elif [[ -e "$PREFIX/config/disabled/$tool" ]]; then
        printf '[已停用]'
    elif ! check_component_links "$tool" >/dev/null 2>&1; then
        printf '[待修复]'
    else
        for binary in $(component_binaries "$tool"); do
            if [[ ( "$tool" == suggestions && ! -r "$PREFIX/bin/$binary" ) ||
                  ( "$tool" != suggestions && ! -x "$PREFIX/bin/$binary" ) ]]; then
                printf '[待修复]'; return 0
            fi
        done
        printf '[已启用]'
    fi
}

menu_snapshot() {
    local kind=$1 tool version
    MENU_TCP=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || true)
    if [[ "$kind" == main ]]; then
        MENU_STATES=()
        for tool in trzsz starship suggestions atuin zoxide; do MENU_STATES+=("$(menu_component_badge "$tool")"); done
    else
        MENU_QDISC=$(sysctl -n net.core.default_qdisc 2>/dev/null || true)
        MENU_KERNEL=$(uname -r)
        version=$(cat /sys/module/tcp_bbr/version 2>/dev/null || true)
        case "$version" in 1|2|3) MENU_VERSION="$version（已加载）" ;; *) MENU_VERSION='未确认（算法名不代表 v3）' ;; esac
    fi
}

menu_prompt() {
    local prompt="请选择：$MENU_INPUT"
    menu_fit "$prompt" "$MENU_WIDTH"
    if [[ "$MENU_TEXT" != "$prompt" ]] && ((MENU_WIDTH >= 3)); then
        menu_fit "$prompt" "$((MENU_WIDTH - 3))"
        MENU_TEXT+='...'
    fi
    printf '%b%s%b' "$MENU_BG$MENU_ACCENT" "$MENU_TEXT" "$MENU_RESET"
    # Shorter input must erase its old suffix. Never emit cursor controls to pipes.
    if [[ "$MENU_READ_KEYS" == 1 ]]; then printf '\033[K'; fi
}

menu_author_credit() {
    local author=tangbaichuan github=https://github.com/reedtang666 caption padding
    caption="作者：$author  |  GitHub：$github"
    menu_fit "$caption" "$MENU_WIDTH"
    if [[ "$MENU_TEXT" != "$caption" ]]; then
        menu_line "作者：$author" "$MENU_ACCENT"
        menu_line "GitHub：$github" "$MENU_CREAM"
        return 0
    fi
    padding=$((MENU_WIDTH - MENU_TEXT_WIDTH))
    printf '%b作者：%b%s%b  |  GitHub：%b%s%*s%b\n' \
        "$MENU_BG$MENU_MUTED" "$MENU_ACCENT" "$author" "$MENU_MUTED" \
        "$MENU_CREAM" "$github" "$padding" '' "$MENU_RESET"
    MENU_LINES=$((MENU_LINES + 1))
}

menu_draw() {
    local kind=$1 bbr_state='[未启用]'
    MENU_LINES=0
    menu_separator
    if [[ "$kind" == main ]]; then
        menu_line 'ShellReady 管理菜单 / 新服务器，一键配顺手' "$MENU_ACCENT"
        menu_line "用户 ${TARGET_USER}  /  ${PRETTY_NAME:-Linux}  /  ${ARCH:-未知架构}" "$MENU_MUTED"
        menu_author_credit
        menu_separator
        menu_section '一键配置'
        menu_item 1 '一键安装全部六项功能' '[推荐]'
        menu_line '      原一键安装保留，默认不更换内核。' "$MENU_MUTED"
        menu_section '功能管理'
        if [[ "$MENU_TCP" == bbr ]]; then bbr_state='[已启用]'; elif [[ -z "$MENU_TCP" ]]; then bbr_state='[未确认]'; fi
        menu_item 2 'BBR 网络管理' "$bbr_state"
        menu_item 3 '文件上传下载  trzsz-go' "${MENU_STATES[0]}"
        menu_item 4 '终端提示符    Starship' "${MENU_STATES[1]}"
        menu_item 5 '命令输入建议  zsh-autosuggestions' "${MENU_STATES[2]}"
        menu_item 6 '历史命令搜索  Atuin' "${MENU_STATES[3]}"
        menu_item 7 '常用目录跳转  zoxide' "${MENU_STATES[4]}"
        menu_section '日常管理'
        menu_item 8 '查看全部功能状态'
        menu_item 9 '修复已安装功能'
        menu_item 10 '卸载 ShellReady' '[需确认]' "$MENU_WARN"
        menu_item 11 '更新 ShellReady' '[需联网]'
        menu_item 0 '退出' '' "$MENU_MUTED"
        menu_separator
        menu_line '状态来自安装/启停记录；终端功能请在 Zsh 中验证。' "$MENU_MUTED"
    else
        menu_line 'ShellReady / BBR 网络管理' "$MENU_ACCENT"
        menu_line "TCP 算法：${MENU_TCP:-不可读取}    默认队列：${MENU_QDISC:-不可读取}"
        menu_line "BBR 版本：$MENU_VERSION" "$MENU_MUTED"
        menu_line "运行内核：$MENU_KERNEL" "$MENU_MUTED"
        menu_author_credit
        menu_separator
        menu_section '状态与启用'
        menu_item 1 '查看 BBR、内核和实际网卡队列' '[只读]'
        menu_item 2 '启用当前内核 BBR'
        menu_item 3 '启用 BBR + FQ（修改出口队列）' '[需确认]'
        menu_section '内核与恢复'
        menu_item 4 '选择标准版 BBRv3 内核安装' '[需重启]'
        menu_item 5 '恢复 ShellReady 修改的网络配置' '[需确认]'
        menu_item 6 '移除已记录的非运行 BBRv3 内核' '[需确认]' "$MENU_WARN"
        menu_line '旧内核保留，不自动重启；默认队列不代表实际出口队列。' "$MENU_MUTED"
        menu_item 0 '返回总菜单' '' "$MENU_MUTED"
        menu_separator
    fi
    if [[ "$MENU_KEYS" == 1 ]]; then
        menu_line '↑↓ 移动 / 数字选择 / Enter 确认 / Esc 返回' "$MENU_MUTED"
    else
        menu_line '输入数字并按 Enter 确认；0 返回或退出。' "$MENU_MUTED"
    fi
    menu_prompt
}

menu_input_restore() {
    [[ "$MENU_TRAPS_SET" == 1 ]] || return 0
    MENU_TRAPS_SET=0
    stty "$MENU_TTY_STATE" 2>/dev/null || true
    trap - INT TERM
    # These strings come only from Bash's own trap -p, not user input or files.
    if [[ -n "$MENU_SAVED_INT" ]]; then eval "$MENU_SAVED_INT"; fi
    if [[ -n "$MENU_SAVED_TERM" ]]; then eval "$MENU_SAVED_TERM"; fi
}

menu_input_interrupt() {
    menu_input_restore
    printf '%b\n' "$MENU_RESET"
    exit "$1"
}

menu_choose() {
    local kind=$1 key next sequence index drawn=0 previous_size typed_choice=1 minimum_rows=24
    local MENU_LINES=0 MENU_SELECTED=0 MENU_INPUT='' MENU_KEYS MENU_READ_KEYS MENU_ROWS MENU_COLUMNS MENU_WIDTH
    local MENU_TCP MENU_QDISC MENU_KERNEL MENU_VERSION MENU_STATES=() options=()
    local MENU_TTY_STATE='' MENU_SAVED_INT='' MENU_SAVED_TERM='' MENU_TRAPS_SET=0
    if [[ "$kind" == main ]]; then
        options=(1 2 3 4 5 6 7 8 9 10 11 0); minimum_rows=25
    else options=(1 2 3 4 5 6 0); fi
    menu_style
    menu_snapshot "$kind"
    menu_dimensions "$minimum_rows"
    if [[ "$MENU_READ_KEYS" == 1 ]]; then
        MENU_TTY_STATE=$(stty -g 2>/dev/null || true)
        if [[ -n "$MENU_TTY_STATE" ]]; then
            MENU_SAVED_INT=$(trap -p INT); MENU_SAVED_TERM=$(trap -p TERM)
            trap 'menu_input_interrupt 130' INT
            trap 'menu_input_interrupt 143' TERM
            MENU_TRAPS_SET=1
        fi
    fi
    printf '\n'
    while :; do
        previous_size="$MENU_ROWS:$MENU_COLUMNS"
        menu_dimensions "$minimum_rows"
        if [[ -z "$MENU_TTY_STATE" ]]; then MENU_KEYS=0; MENU_READ_KEYS=0; fi
        if [[ "$drawn" == 1 && "$previous_size" == "$MENU_ROWS:$MENU_COLUMNS" ]]; then
            if [[ "$MENU_KEYS" == 1 ]]; then
                printf '\r\033[%sA' "$MENU_LINES"
                menu_draw "$kind"
            else
                # A small window scrolls the menu. Edit only the prompt there.
                printf '\r'
                menu_prompt
            fi
        else
            if [[ "$drawn" == 1 ]]; then printf '\n'; fi
            menu_draw "$kind"
        fi
        if [[ "$MENU_READ_KEYS" == 0 ]]; then
            IFS= read -r MENU_CHOICE || { menu_input_restore; printf '\n'; return 1; }
            MENU_CHOICE=$MENU_INPUT$MENU_CHOICE
            menu_input_restore; printf '\n'; return 0
        fi
        drawn=1
        IFS= read -rsn1 key || { menu_input_restore; printf '\n'; return 1; }
        case "$key" in
            ''|$'\r') MENU_CHOICE=${MENU_INPUT:-$MENU_SELECTED}; menu_input_restore; printf '\n'; return 0 ;;
            $'\004') menu_input_restore; printf '\n'; return 1 ;;
            $'\033')
                sequence=''
                if ! IFS= read -rsn1 -t 1 next; then MENU_CHOICE=0; menu_input_restore; printf '\n'; return 0; fi
                if [[ "$next" == '[' ]]; then
                    # Consume the whole CSI, including modifiers/Delete/Page keys.
                    # Only plain cursor up/down are mapped to menu navigation.
                    while IFS= read -rsn1 -t 1 next; do
                        sequence+=$next
                        case "$next" in [@-~]) break ;; ''|$'\r') sequence=''; break ;; esac
                    done
                elif [[ "$next" == O ]]; then
                    IFS= read -rsn1 -t 1 sequence || true
                fi
                if [[ "$MENU_KEYS" == 1 && ( "$sequence" == A || "$sequence" == B ) ]]; then
                    index=0
                    while ((index < ${#options[@]} - 1)) && [[ "${options[$index]}" != "$MENU_SELECTED" ]]; do index=$((index + 1)); done
                    if [[ "$sequence" == A ]]; then index=$(((index + ${#options[@]} - 1) % ${#options[@]}));
                    else index=$(((index + 1) % ${#options[@]})); fi
                    MENU_SELECTED=${options[$index]}; MENU_INPUT=$MENU_SELECTED
                    typed_choice=0
                fi ;;
            $'\177'|$'\010') MENU_INPUT=${MENU_INPUT%?}; MENU_SELECTED=${MENU_INPUT:-0}; typed_choice=1 ;;
            [[:print:]])
                if [[ "$typed_choice" == 0 ]]; then MENU_INPUT=''; fi
                MENU_INPUT+=$key; MENU_SELECTED=$MENU_INPUT; typed_choice=1 ;;
        esac
    done
}

# Menus only dispatch commands; each mutation gets its own permission/lock scope.
menu_action() {
    local args=("$@" --user "$TARGET_USER")
    [[ "$KEEP_SHELL" == 0 ]] || args+=(--keep-shell)
    [[ "$SKIP_BBR" == 0 ]] || args+=(--skip-bbr)
    bash "$ROOT/install.sh" "${args[@]}" </dev/null
}

menu_run() {
    local rc=0
    menu_action "$@" || rc=$?
    if [[ "$rc" != 0 ]]; then
        case "$1:${3:-}" in
            install:|update:|repair:|component:install) MENU_SHELL_READY=0 ;;
        esac
    fi
    case "$rc" in
        0)
            case "$1:${3:-}" in
                install:|update:|repair:|component:install)
                    if [[ "$KEEP_SHELL" == 0 && -t 0 && -t 1 ]]; then
                        if [[ "${MENU_SHELL_READY:-0}" != 1 ]]; then
                            log '退出总菜单后会自动进入 Zsh，无需重新连接 SSH。'
                        fi
                        MENU_SHELL_READY=1
                    fi ;;
            esac ;;
        2) log '部分操作已跳过或待验证，详情见上方。' ;;
        *) log "操作失败（退出码 ${rc}），可修复原因后重试。" ;;
    esac
}

menu_confirm() {
    local answer
    printf '%s [y/N]：' "$1"
    IFS= read -r answer || return 1
    [[ "$answer" == y || "$answer" == Y ]]
}

component_menu() {
    local tool=$1 title=$2 choice
    while :; do
        printf '\n%s\n' "$title"
        component_status "$tool" || true
        printf '1. 安装或修复\n2. 启用\n3. 停用\n4. 卸载工具（保留历史和配置）\n0. 返回总菜单\n请选择：'
        IFS= read -r choice || return 0
        case "$choice" in
            1) menu_run component "$tool" install ;;
            2) menu_run component "$tool" enable ;;
            3) menu_run component "$tool" disable ;;
            4) if menu_confirm "卸载 ${title}，保留历史和配置？"; then menu_run component "$tool" remove; fi ;;
            0) return 0 ;;
            *) log '无效选项，请重新选择。' ;;
        esac
    done
}

menu_kernel_install() {
    local tags tag choice index
    local versions=()
    tags=$(kernel_release_tags) || { log '获取版本列表失败，未安装内核。'; return 0; }
    while IFS= read -r tag; do [[ -z "$tag" ]] || versions+=("$tag"); done <<< "$tags"
    for index in "${!versions[@]}"; do printf '%s. %s\n' "$((index + 1))" "${versions[$index]}"; done
    printf '选择标准版编号（0 返回）：'
    IFS= read -r choice || return 0
    [[ "$choice" != 0 ]] || return 0
    [[ "$choice" =~ ^[0-9]{1,3}$ ]] || { log '无效版本编号。'; return 0; }
    index=$((10#$choice - 1))
    ((index >= 0 && index < ${#versions[@]})) || { log '无效版本编号。'; return 0; }
    tag=${versions[$index]}
    if menu_confirm "安装 ${tag}？将更换服务器内核，保留旧内核，不自动重启"; then
        menu_run bbrv3 --tag "$tag" --yes
    fi
}

menu_kernel_remove() {
    local tag
    menu_run kernel-list
    printf '输入要移除的已记录标准版 tag（留空返回）：'
    IFS= read -r tag || return 0
    [[ -n "$tag" ]] || return 0
    if menu_confirm "移除 ${tag}？正在运行的内核不能移除"; then
        menu_run kernel-remove --tag "$tag" --yes
    fi
}

bbr_menu() {
    local choice
    while :; do
        menu_choose bbr || return 0
        choice=$MENU_CHOICE
        case "$choice" in
            1) menu_run bbr-status ;;
            2) menu_run bbr-enable ;;
            3) if menu_confirm '启用 BBR + FQ？会影响全机网络，已有自定义队列时跳过'; then menu_run bbr-fq --yes; fi ;;
            4) menu_kernel_install ;;
            5) if menu_confirm '恢复 ShellReady 保存的网络原配置？'; then menu_run bbr-restore --yes; fi ;;
            6) menu_kernel_remove ;;
            0) return 0 ;;
            *) log '无效选项，请重新选择。' ;;
        esac
    done
}

main_menu() {
    local choice update_rc
    MENU_SHELL_READY=0
    while :; do
        menu_choose main || return 0
        choice=$MENU_CHOICE
        case "$choice" in
            1) menu_run install ;;
            2) bbr_menu ;;
            3) component_menu trzsz '文件上传下载（trzsz-go）' ;;
            4) component_menu starship '终端提示符（Starship）' ;;
            5) component_menu suggestions '命令输入建议（zsh-autosuggestions）' ;;
            6) component_menu atuin '历史命令搜索（Atuin）' ;;
            7) component_menu zoxide '常用目录跳转（zoxide）' ;;
            8) menu_run status ;;
            9) menu_run repair ;;
            10)
                if menu_confirm '卸载 ShellReady？保留历史、配置备份和全机 BBR/内核'; then
                    # The installed menu's own source may have been removed.
                    if menu_action uninstall; then MENU_SHELL_READY=0; return 0; else log '卸载失败，请查看上方原因。'; fi
                fi ;;
            11)
                if menu_confirm '从项目 main 更新 ShellReady 并修复已装组件？保留历史/停用状态，不处理 BBR、内核或登录 Shell'; then
                    update_rc=0
                    menu_action self-update || update_rc=$?
                    case "$update_rc" in
                        0) MENU_SHELL_READY=0; log '更新完成；已退出旧菜单，请输入 shellready 打开新版。'; return 0 ;;
                        2) MENU_SHELL_READY=0; log '更新存在跳过或待验证项，请检查上方结果；已退出旧菜单，可输入 shellready 重新检查。'; return 0 ;;
                        *) log "更新失败（退出码 ${update_rc}），请查看上方原因，可修复后重试。" ;;
                    esac
                fi ;;
            0) return 0 ;;
            *) log '无效选项，请重新选择。' ;;
        esac
    done
}
