#!/usr/bin/env bash
# Standalone entry and shared helpers. Sourcing never starts installation.

# slant lettering from the project's ASCII-Art-Generator result (51 columns).
# Keep this in the standalone entry so downloads and installed menus share it.
shellready_logo() {
    cat <<'EOF'
         __         ____                    __
   _____/ /_  ___  / / /_______  ____ _____/ /_  __
  / ___/ __ \/ _ \/ / / ___/ _ \/ __ `/ __  / / / /
 (__  ) / / /  __/ / / /  /  __/ /_/ / /_/ / /_/ /
/____/_/ /_/\___/_/_/_/   \___/\__,_/\__,_/\__, /
                                          /____/
EOF
}

shellready_banner() {
    local size rows columns line color='' reset=''
    rows=24; columns=80
    if [[ -t 1 && ${TERM:-dumb} != dumb ]]; then
        # Preserve stdout before command substitution turns it into a pipe.
        # Menu actions have /dev/null stdin, so stty must use the output terminal.
        { size=$(stty size <&3 2>/dev/null || true); } 3<&1
        read -r rows columns <<< "$size" || true
        [[ "$rows" =~ ^[1-9][0-9]{0,3}$ ]] || rows=24
        [[ "$columns" =~ ^[1-9][0-9]{0,3}$ ]] || columns=80
        if [[ -z ${NO_COLOR:-} ]]; then
            reset=$'\033[0m'
            case "${COLORTERM:-}:${TERM:-}" in
                truecolor:*|24bit:*|*:*direct*) color=$'\033[38;2;241;198;94m' ;;
                *:*-256color*) color=$'\033[38;5;221m' ;;
                *) color=$'\033[33m' ;;
            esac
        fi
    fi
    if [[ -t 1 && ${TERM:-dumb} != dumb ]] && ((columns >= 52 && rows >= 10)); then
        while IFS= read -r line; do
            printf '%b%s%b\n' "$color" "$line" "$reset"
        done < <(shellready_logo)
    else
        printf '%bShellReady%b\n' "$color" "$reset"
    fi
    printf '%b新服务器，一键配顺手。%b\n\n' "$color" "$reset"
}

shellready_download_config() {
    export SHELLREADY_DOWNLOAD_MODE=${SHELLREADY_DOWNLOAD_MODE:-auto}
    export SHELLREADY_GITHUB_MIRROR=${SHELLREADY_GITHUB_MIRROR:-https://gh-proxy.com}
    case "$SHELLREADY_DOWNLOAD_MODE" in
        auto|cn|direct) ;;
        *) echo 'SHELLREADY_DOWNLOAD_MODE 必须为 auto、cn 或 direct' >&2; return 1 ;;
    esac
    # Public HTTPS prefixes only; these values also cross sudo and enter the manager.
    [[ "$SHELLREADY_GITHUB_MIRROR" =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?(/[a-zA-Z0-9._~/-]*)?$ ]] || {
        echo 'SHELLREADY_GITHUB_MIRROR 必须为不含凭据、查询参数的 HTTPS 镜像前缀' >&2; return 1
    }
    SHELLREADY_GITHUB_MIRROR=${SHELLREADY_GITHUB_MIRROR%/}
}

shellready_download_urls() {
    local url=$1 upstream=$1 cdn=''
    local mirrors=()
    case "$url" in
        https://github.com/*|https://api.github.com/*|https://raw.githubusercontent.com/*|https://codeload.github.com/*)
            if [[ "$url" =~ ^https://raw.githubusercontent.com/([^/]+)/([^/]+)/([^/]+)/(.+)$ ]]; then
                cdn="https://cdn.jsdelivr.net/gh/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}@${BASH_REMATCH[3]}/${BASH_REMATCH[4]}"
                mirrors+=("$cdn")
            elif [[ "$url" =~ ^https://codeload.github.com/([^/]+)/([^/]+)/tar.gz/(.+)$ ]]; then
                upstream="https://github.com/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}/archive/${BASH_REMATCH[3]}.tar.gz"
            fi
            mirrors+=("$SHELLREADY_GITHUB_MIRROR/$upstream")
            # Public download mirrors can exhaust their shared GitHub API quota.
            if [[ "$url" == https://api.github.com/* ]]; then
                mirrors+=("https://gh-api.p3terx.com/${url#https://api.github.com/}")
            fi ;;
    esac
    if [[ "$SHELLREADY_DOWNLOAD_MODE" != cn ]]; then printf '%s\n' "$url"; fi
    if [[ "$SHELLREADY_DOWNLOAD_MODE" != direct && ${#mirrors[@]} -gt 0 ]]; then
        printf '%s\n' "${mirrors[@]}"
    fi
    if [[ "$SHELLREADY_DOWNLOAD_MODE" == cn ]]; then printf '%s\n' "$url"; fi
}

shellready_fetch() {
    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --proto-redir '=https' -fL --retry 1 --retry-delay 1 \
            --connect-timeout 8 --max-time "$3" --speed-time 20 --speed-limit 1024 "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget --https-only --tries=2 --timeout=20 "$1" -O "$2"
    else
        echo '需要 curl 或 wget' >&2; return 1
    fi
}

shellready_download() {
    local url=$1 dest=$2 timeout=${3:-900} candidate
    shellready_download_config || return 1
    [[ "$url" == https://* ]] || { echo '下载仅接受 HTTPS' >&2; return 1; }
    while IFS= read -r candidate; do
        rm -f -- "$dest.part" || return 1
        printf '[ShellReady] 下载：%s\n' "$candidate" >&2
        if shellready_fetch "$candidate" "$dest.part" "$timeout"; then
            mv -- "$dest.part" "$dest" && return 0
            rm -f -- "$dest.part"
            return 1
        fi
        rm -f -- "$dest.part" || return 1
    done < <(shellready_download_urls "$url")
    echo '所有候选下载地址均失败，请检查网络或设置 SHELLREADY_GITHUB_MIRROR。' >&2
    return 1
}

shellready_bootstrap() (
    set -euo pipefail
    # Help stays plain; all other remote invocations show branding before downloads.
    show_banner=1
    for arg in "$@"; do
        case "$arg" in --help|-h) show_banner=0 ;; esac
    done
    if [[ "$show_banner" == 1 ]]; then shellready_banner; fi
    REPO=9star-academy/ShellReady
    REF=${SHELLREADY_REF:-main}
    [[ "$REF" =~ ^[a-zA-Z0-9._/-]+$ && "$REF" != -* ]] || { echo '无效仓库 ref' >&2; exit 1; }
    shellready_download_config || exit 1
    if ! command -v tar >/dev/null || ! command -v gzip >/dev/null; then
        echo '需要 tar 和 gzip' >&2; exit 1
    fi
    WORK=$(mktemp -d) || exit 1
    trap 'rm -rf -- "$WORK"' EXIT
    COMMIT=''
    if [[ "$REF" =~ ^[0-9a-f]{40}$ ]]; then
        COMMIT=$REF
    elif [[ "$SHELLREADY_DOWNLOAD_MODE" != cn ]]; then
        if shellready_download "https://api.github.com/repos/$REPO/commits/$REF" "$WORK/commit.json" 30; then
            # Consume all matches to avoid pipefail/SIGPIPE on large responses.
            COMMIT=$(sed -n 's/^[[:space:]]*"sha": "\([0-9a-f]\{40\}\)",.*/\1/p' "$WORK/commit.json" | sed -n '1p')
            [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo '无法解析 commit（可能触发 GitHub API 限额）' >&2; exit 1; }
        elif [[ "$SHELLREADY_DOWNLOAD_MODE" == direct ]]; then
            exit 1
        else
            echo '[ShellReady] commit API 不可用，改用源码归档内的 commit。' >&2
        fi
    fi
    # One archive contains the entire snapshot, even if main moves during download.
    shellready_download "https://codeload.github.com/$REPO/tar.gz/${COMMIT:-$REF}" "$WORK/source.tar.gz" 180 || exit 1
    gzip -dc "$WORK/source.tar.gz" > "$WORK/source.tar" || exit 1
    ARCHIVE_COMMIT=''
    # GitHub git-archive places its full commit in the first global PAX header.
    if [[ $(dd if="$WORK/source.tar" bs=1 skip=156 count=1 2>/dev/null) == g ]]; then
        ARCHIVE_COMMIT=$(dd if="$WORK/source.tar" bs=512 skip=1 count=1 2>/dev/null |
            tr '\000' '\n' | sed -n 's/^[0-9][0-9]* comment=\([0-9a-f]\{40\}\)$/\1/p')
    fi
    if [[ -z "$COMMIT" ]]; then
        [[ "$ARCHIVE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo '源码归档缺少有效 commit，拒绝执行。' >&2; exit 1; }
        COMMIT=$ARCHIVE_COMMIT
    elif [[ -n "$ARCHIVE_COMMIT" && "$ARCHIVE_COMMIT" != "$COMMIT" ]]; then
        echo '源码归档 commit 与请求版本不符，拒绝执行。' >&2; exit 1
    fi
    mkdir "$WORK/source" || exit 1
    # Only the installer may return 2 for skipped/pending work.
    tar -xf "$WORK/source.tar" --strip-components=1 -C "$WORK/source" || exit 1
    printf 'ShellReady snapshot: %s\n' "$COMMIT"
    SHELLREADY_BOOTSTRAP_BANNER=1 bash "$WORK/source/install.sh" "$@"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    shellready_bootstrap "$@"
fi
