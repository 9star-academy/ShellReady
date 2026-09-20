#!/usr/bin/env bash
# Downloads one immutable repository snapshot, then runs its local installer.
set -euo pipefail
REPO=9star-academy/ShellReady
REF=${SHELLREADY_REF:-main}
[[ "$REF" =~ ^[a-zA-Z0-9._/-]+$ && "$REF" != -* ]] || { echo '无效仓库 ref' >&2; exit 1; }
command -v tar >/dev/null || { echo '需要 tar' >&2; exit 1; }
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
fetch() {
    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --proto-redir '=https' -fL --retry 3 --connect-timeout 15 --max-time 180 "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget --https-only --tries=3 --timeout=60 "$1" -O "$2"
    else
        echo '需要 curl 或 wget' >&2; return 1
    fi
}
fetch "https://api.github.com/repos/$REPO/commits/$REF" "$WORK/commit.json"
COMMIT=$(sed -n 's/^[[:space:]]*"sha": "\([0-9a-f]\{40\}\)",.*/\1/p' "$WORK/commit.json" | head -n 1)
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo '无法解析 commit（可能触发 GitHub API 限额）' >&2; exit 1; }
fetch "https://codeload.github.com/$REPO/tar.gz/$COMMIT" "$WORK/source.tar.gz"
mkdir "$WORK/source"
tar -xzf "$WORK/source.tar.gz" --strip-components=1 -C "$WORK/source"
printf 'ShellReady snapshot: %s\n' "$COMMIT"
bash "$WORK/source/install.sh" "$@"
