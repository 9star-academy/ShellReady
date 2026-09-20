#!/usr/bin/env bash
install_tool() {
    local tool=$1 row version url hash dest archive path binary
    row=$(awk -F '\t' -v t="$tool" -v a="$ARCH" '$1==t && ($3==a || $3=="any") {print}' "$ROOT/config/assets.tsv")
    [[ -n "$row" ]] || { fail "没有匹配产物：$tool / $ARCH"; return 1; }
    IFS=$'\t' read -r _ version _ url hash <<< "$row"
    dest="$PREFIX/tools/$tool-$version-${hash:0:12}"
    case "$tool" in
        trzsz) local bins=(trz tsz) ;;
        suggestions) local bins=(zsh-autosuggestions.zsh) ;;
        *) local bins=("$tool") ;;
    esac
    local ready=1
    [[ -f "$dest/.complete" && $(cat "$dest/.complete") == "$hash" ]] || ready=0
    for binary in "${bins[@]}"; do
        if [[ ! -f "$dest/$binary" ]]; then
            ready=0
        elif [[ "$tool" != suggestions ]] && ! as_user "$dest/$binary" --version >/dev/null 2>&1; then
            ready=0
        fi
    done
    if [[ "$ready" == 0 ]]; then
        archive="$WORK/$tool.download"
        download "$url" "$archive"
        verify_sha256 "$archive" "$hash"
        mkdir -p "$WORK/$tool"
        if [[ "$tool" == suggestions ]]; then
            cp "$archive" "$WORK/$tool/zsh-autosuggestions.zsh"
        else
            tar -xzf "$archive" --no-same-owner --no-same-permissions -C "$WORK/$tool"
        fi
        as_user mkdir -p "$dest"
        for binary in "${bins[@]}"; do
            path=$(find "$WORK/$tool" -type f -name "$binary")
            [[ -n "$path" && "$path" != *$'\n'* ]] || { fail "产物中未找到唯一的 $binary"; return 1; }
            user_write "$dest/$binary" "$path"
            as_user chmod 755 "$dest/$binary"
            if [[ "$tool" != suggestions ]]; then
                as_user "$dest/$binary" --version
            fi
        done
        printf '%s\n' "$hash" > "$WORK/receipt"
        user_write "$dest/.complete" "$WORK/receipt"
    fi
    for binary in "${bins[@]}"; do
        [[ -f "$dest/$binary" ]] || { fail "$binary 缺失"; return 1; }
        [[ ! -d "$PREFIX/bin/$binary" || -L "$PREFIX/bin/$binary" ]] || { fail "工具入口被目录占用：$binary"; return 1; }
        as_user ln -sfn "$dest/$binary" "$PREFIX/bin/$binary"
    done
    log "$tool $version 已就绪"
}
install_trzsz() { install_tool trzsz; }
install_starship() { install_tool starship; }
install_suggestions() { install_tool suggestions; }
install_atuin() { install_tool atuin; }
install_zoxide() { install_tool zoxide; }

install_manager() {
    local rel dir
    for rel in install.sh lib/common.sh modules/tools.sh modules/shell.sh modules/bbr.sh modules/kernel.sh \
        config/assets.tsv config/init.zsh config/starship.toml config/atuin/config.toml; do
        dir=$(dirname "$rel")
        as_user mkdir -p "$PREFIX/app/$dir"
        user_write "$PREFIX/app/$rel" "$ROOT/$rel"
    done
    cat > "$WORK/manager" <<'EOF'
#!/usr/bin/env bash
directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec bash "$directory/../app/install.sh" "$@"
EOF
    user_write "$PREFIX/bin/shellready" "$WORK/manager"
    as_user chmod 755 "$PREFIX/bin/shellready"
}
