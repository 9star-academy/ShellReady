#!/usr/bin/env bash
check_shell_block() {
    local file=$1
    [[ ! -L "$file" ]] || { fail "配置是符号链接，请先手动整理：$file"; return 1; }
    [[ ! -e "$file" || -f "$file" ]] || { fail "配置不是普通文件：$file"; return 1; }
    [[ -f "$file" ]] || return 0
    awk '
      /^# >>> ShellReady >>>$/ { if (open || seen) exit 1; open=1; seen=1; next }
      /^# <<< ShellReady <<<$/{ if (!open) exit 1; open=0 }
      END { if (open) exit 1 }
    ' "$file" || { fail "ShellReady 接入段损坏，保留原文件：$file"; return 1; }
}
shell_block() {
    cat <<'EOF'
# >>> ShellReady >>>
[[ -r "$HOME/.local/share/shellready/config/init.zsh" ]] && source "$HOME/.local/share/shellready/config/init.zsh"
# <<< ShellReady <<<
EOF
}
shell_block_is_current() {
    local file=$1 current
    check_shell_block "$file" || return 1
    [[ -f "$file" ]] || return 1
    current=$(awk '/^# >>> ShellReady >>>$/ {copy=1} copy {print} /^# <<< ShellReady <<<$/{copy=0}' "$file") || return 1
    [[ "$current" == "$(shell_block)" ]]
}
remove_shell_block() {
    local file=$1
    check_shell_block "$file" || return 1
    [[ -f "$file" ]] || return 0
    awk '/^# >>> ShellReady >>>$/ {skip=1; next} /^# <<< ShellReady <<<$/{skip=0; next} !skip {print}' "$file" > "$WORK/zshrc.clean" || return 1
    user_write "$file" "$WORK/zshrc.clean"
}
add_shell_block() {
    local file=$1
    check_shell_block "$file" || return 1
    as_user mkdir -p "$STATE/backups"
    if shell_block_is_current "$file"; then
        return 0
    fi
    if [[ -f "$file" ]]; then
        as_user cp -p "$file" "$STATE/backups/zshrc.$(date +%s).$$"
        if grep -q '^# >>> ShellReady >>>$' "$file"; then
            # Replace the managed block in place so later user overrides keep their order.
            shell_block > "$WORK/shellready.block"
            awk -v block_file="$WORK/shellready.block" '
              /^# >>> ShellReady >>>$/ {
                while ((getline line < block_file) > 0) print line
                close(block_file); skip=1; next
              }
              /^# <<< ShellReady <<<$/{skip=0; next}
              !skip {print}
            ' "$file" > "$WORK/zshrc.new"
            user_write "$file" "$WORK/zshrc.new"
            return
        fi
        cat "$file" > "$WORK/zshrc.new"
        printf '\n' >> "$WORK/zshrc.new"
    else
        : > "$WORK/zshrc.new"
    fi
    shell_block >> "$WORK/zshrc.new"
    user_write "$file" "$WORK/zshrc.new"
}

install_shell() {
    local resolved current
    # Respect ZDOTDIR rather than silently updating a file Zsh will never load.
    # Expand HOME/ZDOTDIR inside the target user shell.
    # shellcheck disable=SC2016
    # Login profiles also affect SSH startup; use a separate descriptor for the
    # result so profile banners cannot be mistaken for the directory.
    resolved=$(as_user zsh -lc 'print -r -- "${ZDOTDIR:-$HOME}" >&3' 3>&1 1>&2)
    [[ "$resolved" == "$TARGET_HOME" ]] || { fail "检测到自定义 ZDOTDIR=${resolved}，首版不自动接入；已保留现有配置。"; return 1; }
    check_shell_block "$TARGET_HOME/.zshrc"
    user_write "$PREFIX/config/init.zsh" "$ROOT/config/init.zsh"
    if [[ ! -e "$PREFIX/config/starship.toml" ]]; then
        user_write "$PREFIX/config/starship.toml" "$ROOT/config/starship.toml"
    fi
    if [[ ! -e "$PREFIX/config/atuin/config.toml" ]]; then
        user_write "$PREFIX/config/atuin/config.toml" "$ROOT/config/atuin/config.toml"
    fi
    # Import pre-existing history once, before switching the login shell.
    if [[ -x "$PREFIX/bin/atuin" && ! -e "$STATE/history-imported" ]]; then
        local history_type history_file
        case "$LOGIN_SHELL" in
            */bash) history_type=bash; history_file="$TARGET_HOME/.bash_history" ;;
            */zsh) history_type=zsh; history_file="$TARGET_HOME/.zsh_history" ;;
            *) history_type=''; history_file='' ;;
        esac
        if [[ -n "$history_file" && -s "$history_file" ]]; then
            as_user env ATUIN_CONFIG_DIR="$PREFIX/config/atuin" HISTFILE="$history_file" \
                "$PREFIX/bin/atuin" import "$history_type"
        fi
        as_user touch "$STATE/history-imported"
    fi
    add_shell_block "$TARGET_HOME/.zshrc"
    if [[ "$KEEP_SHELL" == 1 ]]; then
        log '已按 --keep-shell 保留登录 Shell 和当前会话；需要使用增强功能时可手动运行 zsh。'
        return 0
    fi
    if [[ "$LOGIN_SHELL" != /bin/zsh && "$LOGIN_SHELL" != /usr/bin/zsh ]]; then
        grep -qxF /bin/zsh /etc/shells || { fail '/bin/zsh 未列入 /etc/shells'; return 1; }
        if [[ ! -f "$STATE/original-shell" ]]; then
            printf '%s\n' "$LOGIN_SHELL" > "$WORK/original-shell"
            user_write "$STATE/original-shell" "$WORK/original-shell"
        fi
        chsh -s /bin/zsh "$TARGET_USER" || { fail '修改登录 Shell 失败，请检查权限后重试。'; return 1; }
    fi
    current=$(getent passwd "$TARGET_USER" | cut -d: -f7) || { fail '无法读取登录 Shell，未确认切换成功。'; return 1; }
    case "$current" in
        /bin/zsh|/usr/bin/zsh) log "登录 Shell 已核验：${current}；以后登录自动使用 Zsh。" ;;
        *) fail "登录 Shell 未切换成功，当前为：${current}。"; return 1 ;;
    esac
}

# Called only after a successful install/repair, outside its lock and scratch dir.
# Menus leave child stdin closed and defer this to the top-level menu's exit.
start_zsh_session() {
    local current rc=0
    [[ "$KEEP_SHELL" == 0 ]] || return 0
    if [[ ! -t 0 || ! -t 1 ]]; then
        log '当前不是交互终端，未自动进入 Zsh；下次登录会使用已设置的登录 Shell。'
        return 0
    fi
    if [[ ! -f "$PREFIX/config/init.zsh" ]] || ! shell_block_is_current "$TARGET_HOME/.zshrc"; then
        log 'Zsh 配置尚未就绪，未自动进入；请运行 shellready repair 检查修复。'
        return 0
    fi
    current=$(getent passwd "$TARGET_USER" | cut -d: -f7) || current=''
    case "$current" in
        /bin/zsh|/usr/bin/zsh) ;;
        *) log '登录 Shell 尚未确认为 Zsh，未自动进入；请运行 shellready repair 检查修复。'; return 0 ;;
    esac
    log "正在进入 ${TARGET_USER} 的 Zsh，无需重新连接 SSH。"
    log '输入 exit 会返回原来的终端；以后登录会自动使用 Zsh。'
    as_user env SHELL="$current" "$current" -il || rc=$?
    if [[ "$rc" != 0 ]]; then log "Zsh 会话已结束（退出码 ${rc}），安装结果不变。"; fi
    log '已返回原来的终端；再次使用 Zsh 可运行 zsh，或重新连接 SSH。'
}

uninstall_shell() {
    local original current
    remove_shell_block "$TARGET_HOME/.zshrc"
    if [[ -f "$STATE/original-shell" ]]; then
        original=$(cat "$STATE/original-shell")
        current=$(getent passwd "$TARGET_USER" | cut -d: -f7)
        if [[ "$current" == /bin/zsh || "$current" == /usr/bin/zsh ]]; then
            if [[ "$original" != /* ]] || ! grep -qxF "$original" /etc/shells; then
                fail '原登录 Shell 不再有效，请先手动恢复'; return 1
            fi
            chsh -s "$original" "$TARGET_USER"
        fi
        as_user rm -f "$STATE/original-shell"
    fi
}
