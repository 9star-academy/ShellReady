#!/usr/bin/env bash
# Bootstrap downloads one commit; only its repair subprocess elevates and locks.
self_update() {
    [[ -f "$PREFIX/.shellready" && ! -L "$PREFIX" ]] || {
        fail '未找到可更新的 ShellReady 安装，请先完成安装。'; return 1
    }
    [[ -f "$ROOT/bootstrap.sh" ]] || {
        fail '更新入口缺失，请使用完整新版源码修复管理入口。'; return 1
    }
    log '正在获取 ShellReady main 最新源码并修复已安装组件；不处理 BBR、内核或登录 Shell。'
    SHELLREADY_REF=main bash "$ROOT/bootstrap.sh" repair --user "$TARGET_USER" --skip-bbr --keep-shell </dev/null
}
