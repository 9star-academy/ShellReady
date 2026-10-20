# ShellReady Self Update Implementation Plan

**Goal:** 总菜单新增 11「更新 ShellReady」，保留已有编号、旧一键安装和旧 update；不提交代码。

**Architecture:** 新增独立 self-update CLI，在提权/变更锁之前调用随管理程序安装的 bootstrap.sh。bootstrap 从项目 main 解析固定 commit 并下载完整快照，新版安装器执行 repair --user 原用户 --skip-bbr --keep-shell，内部按原规则提权与加锁。菜单确认后分派该 CLI；成功或部分完成后退出旧菜单并提示重新运行 shellready，失败返回菜单。不增加下载框架或工具升级来源。

**Tech Stack:** 现有 Bash、bootstrap、curl/wget、tar、Python unittest/PTY。

## 1. 失败测试
- 新建 tests/test_self_update.py：离线替代 HTTP 边界，验证 main 固定提交、目标用户/参数、输入隔离、下载失败、临时目录清理、安装前置条件和退出码。
- 修改 tests/test_menu.py、tests/test_menu_style.py：确认/取消/失败/退出旧菜单、11 的数字与方向键、25 行主菜单重绘。
- 修改 tests/test_management_cli.py：self-update 不持有外层锁、不直接提权或执行全量安装。

## 2. 最小实现
- 新建 modules/update.sh；install.sh 加载并分派 self-update，旧 update/默认 install 保持原义。
- modules/tools.sh 的管理器复制清单加入 bootstrap.sh 和 modules/update.sh。
- modules/menu.sh 新增选项 11，原 10 卸载不变；主菜单最小方向键窗口为 25 行，BBR 仍为 24 行。
- 更新测试快照复制清单，使其包含完整 bootstrap 源文件。

## 3. 集成与验证
- 用真实缓存组件、安装入口、已安装管理器、菜单、bootstrap 和新快照 repair 连续运行更新；仅替代 OS/包管理/HTTP 边界。核验停用状态、用户数据、未补装组件、网络未改和单层锁。
- 执行 python3 -m unittest discover -s tests -v、bash tests/check.sh、git diff --check。
- README、agent.md、docs/verification.md 说明一次性升级旧安装、菜单更新、self-update 与旧 update 的区别和实机边界。未暂存、未提交、未推送。

## 执行结果

- 总菜单 11、self-update CLI、bootstrap/模块安装清单和单层锁分派完成，旧入口含义与已有编号保留。
- 离线真实更新链覆盖管理器、旧菜单、新快照和 repair，核验实际文件更新及用户状态保留；源码下载失败不进入修复，修复阶段的非事务性边界已记录。
- 170 项测试与 Bash/Zsh/ShellCheck/空白检查通过；真实 GitHub、Linux sudo/apt/flock 与 SSH 更新仍待验收。
- 未暂存、未提交、未推送。
