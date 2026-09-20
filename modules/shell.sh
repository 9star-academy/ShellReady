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
    if [[ -f "$file" ]] && grep -q '^# >>> ShellReady >>>$' "$file"; then
        return 0
    fi
    if [[ -f "$file" ]]; then
        as_user cp -p "$file" "$STATE/backups/zshrc.$(date +%s).$$"
        cat "$file" > "$WORK/zshrc.new"
        printf '\n' >> "$WORK/zshrc.new"
    else
        : > "$WORK/zshrc.new"
    fi
    cat >> "$WORK/zshrc.new" <<'EOF'
# >>> ShellReady >>>
[[ -r "$HOME/.local/share/shellready/config/init.zsh" ]] && source "$HOME/.local/share/shellready/config/init.zsh"
# <<< ShellReady <<<
EOF
    user_write "$file" "$WORK/zshrc.new"
}

install_shell() {
    local resolved
    # Respect ZDOTDIR rather than silently updating a file Zsh will never load.
    # Expand HOME/ZDOTDIR inside the target user shell.
    # shellcheck disable=SC2016
    resolved=$(as_user zsh -c 'print -r -- "${ZDOTDIR:-$HOME}"')
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
    if [[ "$KEEP_SHELL" == 0 && "$LOGIN_SHELL" != /bin/zsh && "$LOGIN_SHELL" != /usr/bin/zsh ]]; then
        grep -qxF /bin/zsh /etc/shells || { fail '/bin/zsh 未列入 /etc/shells'; return 1; }
        if [[ ! -f "$STATE/original-shell" ]]; then
            printf '%s\n' "$LOGIN_SHELL" > "$WORK/original-shell"
            user_write "$STATE/original-shell" "$WORK/original-shell"
        fi
        chsh -s /bin/zsh "$TARGET_USER"
        log '已设为 Zsh；重新连接 SSH 后生效。'
    fi
}

uninstall_shell() {
    local original current
    remove_shell_block "$TARGET_HOME/.zshrc"
    if [[ -f "$STATE/original-shell" ]]; then
        original=$(cat "$STATE/original-shell")
        current=$(getent passwd "$TARGET_USER" | cut -d: -f7)
        if [[ "$current" == /bin/zsh ]]; then
            if [[ "$original" != /* ]] || ! grep -qxF "$original" /etc/shells; then
                fail '原登录 Shell 不再有效，请先手动恢复'; return 1
            fi
            chsh -s "$original" "$TARGET_USER"
        fi
        as_user rm -f "$STATE/original-shell"
    fi
}
