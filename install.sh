#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"
# shellcheck source=modules/tools.sh
source "$ROOT/modules/tools.sh"
# shellcheck source=modules/shell.sh
source "$ROOT/modules/shell.sh"
# shellcheck source=modules/bbr.sh
source "$ROOT/modules/bbr.sh"
# shellcheck source=modules/kernel.sh
source "$ROOT/modules/kernel.sh"

usage() {
    cat <<'EOF'
ShellReady — 新服务器，一键配顺手
用法：bash install.sh [install|update|status|uninstall|bbrv3|kernel-remove] [选项]

  install / update    安装清单固定版本、修复接入配置（默认 install）
  status              只读检查工具、Shell 与 BBR 状态
  uninstall           移除用户工具和接入段，保留历史、备份、系统依赖及内核
  bbrv3               独立安装标准 BBRv3 内核，需要 --tag；不自动重启
  kernel-remove       移除 ShellReady 记录的非运行内核，需要 --tag

  --user NAME         目标用户；默认 sudo 原用户或当前用户
  --keep-shell        不修改登录 Shell，安装后手动运行 zsh
  --skip-bbr          跳过系统 BBR 配置（例如普通容器测试）
  --restore-bbr       仅用于 uninstall，恢复全机 BBR 原配置
  --tag RELEASE       指定 byJoey/Actions-bbr-v3 标准 release tag
  --yes               确认 bbrv3 / kernel-remove 的内核变更
  --help              显示帮助

退出码：0 成功；1 失败；2 部分跳过/尚未就绪。
内核升级会影响整台服务器；重启与真实 SSH/传输验证由用户执行。
EOF
}

ACTION=install
TARGET_USER=${SUDO_USER:-$(id -un)}
KEEP_SHELL=0
SKIP_BBR=0
RESTORE_BBR=0
TAG=''
YES=0
ACTION_SET=0
while (($#)); do
    case "$1" in
        install|update|status|uninstall|bbrv3|kernel-remove)
            [[ "$ACTION_SET" == 0 ]] || { fail '只能指定一个操作'; exit 1; }
            ACTION=$1; ACTION_SET=1; shift ;;
        --user|--tag)
            (($# >= 2)) && [[ -n "$2" && "$2" != -* ]] || { fail "$1 缺少参数"; exit 1; }
            if [[ "$1" == --user ]]; then TARGET_USER=$2; else TAG=$2; fi
            shift 2 ;;
        --keep-shell) KEEP_SHELL=1; shift ;;
        --skip-bbr) SKIP_BBR=1; shift ;;
        --restore-bbr) RESTORE_BBR=1; shift ;;
        --yes) YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "未知参数：$1"; exit 1 ;;
    esac
done
[[ "$RESTORE_BBR" == 0 || "$ACTION" == uninstall ]] || { fail '--restore-bbr 仅用于 uninstall'; exit 1; }
[[ -z "$TAG" || "$ACTION" == bbrv3 || "$ACTION" == kernel-remove ]] || { fail '--tag 仅用于内核操作'; exit 1; }
if [[ "$ACTION" == bbrv3 || "$ACTION" == kernel-remove ]]; then
    [[ -n "$TAG" && "$YES" == 1 ]] || { fail '内核操作必须同时指定 --tag 和 --yes；不会自动重启'; exit 1; }
fi
check_platform
resolve_user
if [[ "$ACTION" != status && $EUID != 0 ]]; then
    command -v sudo >/dev/null 2>&1 || { fail '需要 root 或 sudo 权限'; exit 1; }
    args=("$ACTION" --user "$TARGET_USER")
    [[ "$KEEP_SHELL" == 0 ]] || args+=(--keep-shell)
    [[ "$SKIP_BBR" == 0 ]] || args+=(--skip-bbr)
    [[ "$RESTORE_BBR" == 0 ]] || args+=(--restore-bbr)
    [[ -z "$TAG" ]] || args+=(--tag "$TAG")
    [[ "$YES" == 0 ]] || args+=(--yes)
    exec sudo bash "$ROOT/install.sh" "${args[@]}"
fi

RESULTS=()
FAILED=0
SKIPPED=0
WORK=''
cleanup() { [[ -z "$WORK" ]] || rm -rf -- "$WORK"; }
trap cleanup EXIT

if [[ "$ACTION" != status ]]; then
    # flock releases on exit, including failures, without stale lock recovery.
    command -v flock >/dev/null 2>&1 || { fail '缺少 flock（util-linux）'; exit 1; }
    install -d -m 700 /run/shellready
    exec 9>/run/shellready/install.lock
    flock -n 9 || { fail '另一个 ShellReady 安装正在运行'; exit 1; }
    WORK=$(mktemp -d /tmp/shellready.XXXXXXXX)
    chmod 700 "$WORK"
fi

install_dependencies() {
    local pkg missing_packages=()
    for pkg in ca-certificates curl tar gzip coreutils zsh passwd util-linux procps kmod; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -qx 'install ok installed'; then
            missing_packages+=("$pkg")
        fi
    done
    if ((${#missing_packages[@]})); then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing_packages[@]}"
    fi
}

status_tools() {
    local binary missing=0
    for binary in trz tsz starship atuin zoxide; do
        if [[ -x "$PREFIX/bin/$binary" ]]; then
            as_user "$PREFIX/bin/$binary" --version || missing=1
        else
            log "$binary 未安装"; missing=1
        fi
    done
    [[ -r "$PREFIX/bin/zsh-autosuggestions.zsh" ]] || { log 'zsh-autosuggestions 未安装'; missing=1; }
    [[ "$missing" == 0 ]] || return 2
}
status_shell() {
    if [[ ! -r "$TARGET_HOME/.zshrc" ]] || ! grep -q '^# >>> ShellReady >>>$' "$TARGET_HOME/.zshrc"; then
        log 'Zsh 接入段不存在'; return 2
    fi
    [[ -f "$PREFIX/config/init.zsh" ]] || { log 'Shell 初始化文件不存在'; return 2; }
    log "Zsh 接入段存在；登录 Shell：${LOGIN_SHELL}。交互效果需重新连接验证。"
}

case "$ACTION" in
    install|update)
        log "目标用户：${TARGET_USER}；home：${TARGET_HOME}；架构：$ARCH"
        install_dependencies
        prepare_user_dirs
        install_manager
        run_step 'trzsz-go' install_trzsz
        run_step 'Starship' install_starship
        run_step 'zsh-autosuggestions' install_suggestions
        run_step 'Atuin' install_atuin
        run_step 'zoxide' install_zoxide
        if [[ "$FAILED" == 0 ]]; then
            run_step 'Zsh 配置与历史导入' install_shell
        else
            RESULTS+=('跳过：Shell 接入（工具未全部安装成功，重跑可继续）')
            SKIPPED=$((SKIPPED + 1))
        fi
        if [[ "$SKIP_BBR" == 0 ]]; then
            run_step '当前内核 BBR' install_bbr
        else
            log '按 --skip-bbr 要求，不处理系统 BBR。'
        fi
        ;;
    status)
        run_step '工具状态' status_tools
        run_step 'Shell 配置状态' status_shell
        run_step 'BBR 状态' status_bbr
        run_step '内核升级状态' status_kernel
        ;;
    uninstall)
        if [[ -f "$PREFIX/.shellready" ]]; then
            run_step '恢复 Shell 接入' uninstall_shell
            if [[ "$FAILED" == 0 ]]; then
                as_user rm -rf -- "$PREFIX"
                log '已移除专属工具目录；保留 Atuin/zoxide 历史、备份和系统依赖。'
            fi
        else
            log '未发现 ShellReady 用户安装，保留现有目录。'
        fi
        [[ "$RESTORE_BBR" == 0 ]] || run_step '恢复全机 BBR' restore_bbr
        ;;
    bbrv3) run_step '安装指定 BBRv3 内核' install_kernel ;;
    kernel-remove) run_step '移除非运行的项目内核' remove_kernel ;;
esac
printf '\n'
if ((${#RESULTS[@]})); then printf '%s\n' "${RESULTS[@]}"; fi
if ((FAILED)); then log "存在 $FAILED 项失败，修复原因后重跑。"; exit 1; fi
if ((SKIPPED)); then log "存在 $SKIPPED 项跳过或待验证，未标记为全部完成。"; exit 2; fi
log '操作完成。'
