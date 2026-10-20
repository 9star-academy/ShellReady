#!/usr/bin/env bash
# Component names are internal identifiers; never execute user-provided names.
validate_component() {
    case "$1" in trzsz|starship|suggestions|atuin|zoxide) return 0 ;; *) fail "未知组件：$1" ;; esac
}

component_binaries() {
    case "$1" in
        trzsz) printf '%s\n' trz tsz ;;
        suggestions) printf '%s\n' zsh-autosuggestions.zsh ;;
        starship|atuin|zoxide) printf '%s\n' "$1" ;;
        *) return 1 ;;
    esac
}

component_dirs() {
    local tool=$1 dir hash
    for dir in "$PREFIX/tools/$tool-"*; do
        [[ -d "$dir" && ! -L "$dir" && -f "$dir/.complete" ]] || continue
        hash=$(cat "$dir/.complete")
        [[ "$hash" =~ ^[0-9a-f]{64}$ && "$dir" == *-"${hash:0:12}" ]] || continue
        printf '%s\n' "$dir"
    done
}

component_installed() {
    local dir binary complete
    while IFS= read -r dir; do
        [[ -n "$dir" ]] || continue
        complete=1
        for binary in $(component_binaries "$1"); do
            if [[ "$1" == suggestions ]]; then
                [[ -r "$dir/$binary" ]] || complete=0
            else
                [[ -x "$dir/$binary" ]] || complete=0
            fi
        done
        [[ "$complete" != 1 ]] || return 0
    done < <(component_dirs "$1")
    return 1
}

component_status() {
    local tool=$1 binary
    if ! component_installed "$tool"; then
        log "${tool}：未安装或产物不完整"; return 2
    fi
    if [[ -e "$PREFIX/config/disabled/$tool" ]]; then
        log "${tool}：已安装 / 已停用（重新连接 SSH 后生效）"
    else
        check_component_links "$tool" || return 1
        for binary in $(component_binaries "$tool"); do
            if [[ ! -e "$PREFIX/bin/$binary" ]]; then
                log "${tool}：已安装 / 入口缺失，请选择安装或修复。"; return 2
            fi
            if [[ "$tool" != suggestions ]]; then
                as_user "$PREFIX/bin/$binary" --version || return 1
            fi
        done
        log "${tool}：已安装 / 已启用（Shell 接入与实际使用需验证）"
    fi
}

# Refuse foreign files before removing or replacing any command entry.
check_component_links() {
    local tool=$1 binary target dir found
    for binary in $(component_binaries "$tool"); do
        [[ -e "$PREFIX/bin/$binary" || -L "$PREFIX/bin/$binary" ]] || continue
        [[ -L "$PREFIX/bin/$binary" ]] || { fail "入口不是项目管理的链接，保留：$PREFIX/bin/$binary"; return 1; }
        target=$(readlink "$PREFIX/bin/$binary")
        found=0
        while IFS= read -r dir; do
            [[ "$target" != "$dir/$binary" ]] || found=1
        done < <(component_dirs "$tool")
        [[ "$found" == 1 ]] || { fail "入口不属于此组件，保留：$PREFIX/bin/$binary"; return 1; }
    done
}

set_component_enabled() {
    local tool=$1 enabled=$2 binary dir selected=''
    component_installed "$tool" || { fail "$tool 尚未安装，请先选择安装或修复"; return 1; }
    check_component_links "$tool" || return 1
    if [[ "$enabled" == 0 ]]; then
        as_user mkdir -p "$PREFIX/config/disabled" || return 1
        as_user touch "$PREFIX/config/disabled/$tool" || return 1
        if [[ "$tool" == trzsz ]]; then
            for binary in $(component_binaries "$tool"); do as_user rm -f "$PREFIX/bin/$binary" || return 1; done
        fi
        log "$tool 已停用；终端功能请重新连接 SSH 后验证。"
    else
        if [[ "$tool" == trzsz ]]; then
            # Prefer the manifest version; otherwise retain the last installed version.
            while IFS= read -r dir; do
                if [[ -x "$dir/trz" && -x "$dir/tsz" ]]; then selected=$dir; fi
            done < <(component_dirs "$tool")
            local version hash
            IFS=$'\t' read -r _ version _ _ hash < <(awk -F '\t' -v t="$tool" -v a="$ARCH" '$1==t && ($3==a || $3=="any") {print}' "$ROOT/config/assets.tsv")
            dir="$PREFIX/tools/$tool-$version-${hash:0:12}"
            if [[ -f "$dir/.complete" && $(cat "$dir/.complete") == "$hash" && -x "$dir/trz" && -x "$dir/tsz" ]]; then selected=$dir; fi
            for binary in $(component_binaries "$tool"); do
                as_user ln -sfn "$selected/$binary" "$PREFIX/bin/$binary" || return 1
            done
        fi
        as_user rm -f "$PREFIX/config/disabled/$tool" || return 1
        log "$tool 已启用；终端功能请重新连接 SSH 后验证。"
    fi
}

# Batch repair installs all selected files before activating their shared Shell.
install_component_files() {
    local tool=$COMPONENT
    check_component_links "$tool" || return 1
    install_tool "$tool" || return 1
    if [[ -e "$PREFIX/config/disabled/$tool" ]]; then set_component_enabled "$tool" 0 || return 1; fi
}

install_component() {
    local tool=$1
    install_dependencies || return 1
    prepare_user_dirs || return 1
    install_manager || return 1
    COMPONENT=$tool install_component_files || return 1
    install_shell
}

remove_component() {
    local tool=$1 binary dir
    check_component_links "$tool" || return 1
    for binary in $(component_binaries "$tool"); do as_user rm -f "$PREFIX/bin/$binary" || return 1; done
    while IFS= read -r dir; do as_user rm -rf -- "$dir" || return 1; done < <(component_dirs "$tool")
    log "$tool 已卸载；保留配置、历史记录和其他组件，重新连接 SSH 后生效。"
}

manage_component() {
    validate_component "$COMPONENT" || return 1
    if [[ "$OPERATION" == status ]]; then component_status "$COMPONENT"; return $?; fi
    if [[ "$OPERATION" == install ]]; then install_component "$COMPONENT"; return $?; fi
    [[ -f "$PREFIX/.shellready" && ! -L "$PREFIX" ]] || { fail '没有可管理的 ShellReady 用户安装'; return 1; }
    case "$OPERATION" in
        enable) set_component_enabled "$COMPONENT" 1 ;;
        disable) set_component_enabled "$COMPONENT" 0 ;;
        remove) remove_component "$COMPONENT" ;;
        *) fail "未知组件操作：$OPERATION" ;;
    esac
}

repair_components() {
    local tool found=0
    [[ -f "$PREFIX/.shellready" ]] || { log '未安装 ShellReady，请先选择全部或单项安装。'; return 2; }
    install_dependencies
    prepare_user_dirs
    install_manager
    for tool in trzsz starship suggestions atuin zoxide; do
        # Include damaged installed artifacts, but do not bring removed tools back.
        if [[ -n $(component_dirs "$tool") ]]; then
            found=1
            COMPONENT=$tool run_step "$tool" install_component_files
        fi
    done
    [[ "$found" == 0 || "$FAILED" != 0 ]] || run_step 'Shell 接入' install_shell
    if [[ "$SKIP_BBR" == 0 && -f "$BBR_STATE/original" ]]; then run_step '已有 BBR 配置' install_bbr; fi
}
