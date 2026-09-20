#!/usr/bin/env bash
# Shared helpers. Functions are also sourced by isolated tests.
log() { printf '[ShellReady] %s\n' "$*"; }
fail() { printf '[ShellReady] %s\n' "$*" >&2; return 1; }

as_user() {
    if [[ "$(id -u)" == "$(id -u "$TARGET_USER")" ]]; then
        env HOME="$TARGET_HOME" USER="$TARGET_USER" LOGNAME="$TARGET_USER" "$@"
    else
        runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" LOGNAME="$TARGET_USER" \
            XDG_CONFIG_HOME="$TARGET_HOME/.config" XDG_DATA_HOME="$TARGET_HOME/.local/share" \
            XDG_STATE_HOME="$TARGET_HOME/.local/state" "$@"
    fi
}

resolve_user() {
    local entry
    entry=$(getent passwd "$TARGET_USER") || { fail "用户不存在：$TARGET_USER"; return 1; }
    TARGET_HOME=$(printf '%s' "$entry" | cut -d: -f6)
    # Used by modules/shell.sh after resolve_user.
    # shellcheck disable=SC2034
    LOGIN_SHELL=$(printf '%s' "$entry" | cut -d: -f7)
    [[ "$TARGET_HOME" == /* && "$TARGET_HOME" != / && -d "$TARGET_HOME" ]] || { fail '目标用户 home 无效'; return 1; }
    PREFIX="$TARGET_HOME/.local/share/shellready"
    STATE="$TARGET_HOME/.local/state/shellready"
}

check_platform() {
    [[ $(uname -s) == Linux ]] || { fail '安装目标必须是 Linux；--help 可在本机查看。'; return 1; }
    # shellcheck disable=SC1091
    source /etc/os-release
    case "$ID:${VERSION_ID:-}" in
        ubuntu:22.04|ubuntu:24.04|debian:12|debian:13) ;;
        *) fail "首版不支持：${PRETTY_NAME:-$ID}"; return 1 ;;
    esac
    # ARCH is consumed by the tool and kernel modules.
    # shellcheck disable=SC2034
    case "$(uname -m)" in
        x86_64) ARCH=x86_64 ;;
        aarch64|arm64) ARCH=aarch64 ;;
        *) fail '首版仅支持 x86_64 / ARM64'; return 1 ;;
    esac
}

download() {
    local url=$1 dest=$2
    [[ "$url" == https://* ]] || { fail '下载仅接受 HTTPS'; return 1; }
    rm -f "$dest.part"
    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --proto-redir '=https' -fL --retry 3 --connect-timeout 15 --max-time 900 -o "$dest.part" "$url" || return 1
    else
        wget --https-only --tries=3 --timeout=60 -O "$dest.part" "$url" || return 1
    fi
    mv "$dest.part" "$dest"
}

verify_sha256() {
    local actual
    [[ "$2" =~ ^[0-9a-f]{64}$ ]] || { fail '无有效 SHA-256，拒绝使用产物'; return 1; }
    if command -v sha256sum >/dev/null 2>&1; then
        actual=$(sha256sum "$1") || return 1
    else
        actual=$(shasum -a 256 "$1") || return 1
    fi
    [[ "${actual%% *}" == "$2" ]] || { fail "SHA-256 不匹配：$1"; return 1; }
}

prepare_user_dirs() {
    if [[ -e "$PREFIX" && ! -f "$PREFIX/.shellready" ]]; then
        fail "目录已存在且不属于 ShellReady：$PREFIX"; return 1
    fi
    as_user mkdir -p "$PREFIX/bin" "$PREFIX/tools" "$PREFIX/config/atuin" "$STATE/backups"
    as_user touch "$PREFIX/.shellready"
    as_user chmod 700 "$STATE" "$STATE/backups"
}

# Atomic replacement while retaining the target user's ownership.
user_write() {
    local dest=$1 src=$2
    [[ ! -L "$dest" ]] || { fail "拒绝覆盖符号链接：$dest"; return 1; }
    # Expansion belongs to the target-user subprocess, not this root shell.
    # shellcheck disable=SC2016
    as_user sh -c '
        umask 077
        tmp=$(mktemp "${1}.XXXXXXXX") || exit 1
        trap '\''rm -f "$tmp"'\'' EXIT
        cat > "$tmp" && chmod 600 "$tmp" && mv -f "$tmp" "$1"
    ' sh "$dest" < "$src"
}

run_step() {
    local label=$1 fn=$2 rc
    log "$label"
    set +e
    (set -e; "$fn")
    rc=$?
    set -e
    case "$rc" in
        0) RESULTS+=("成功：$label") ;;
        2) RESULTS+=("跳过：${label}（见上方原因）"); SKIPPED=$((SKIPPED + 1)) ;;
        *) RESULTS+=("失败：${label}（见上方原因）"); FAILED=$((FAILED + 1)) ;;
    esac
}
