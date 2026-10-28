# Zsh 自动进入与提示 Implementation Plan

> 按已在对话中确认的方案直接在当前工作区实施；不提交、不推送。

**Goal:** 交互终端安装成功后自动以目标用户进入 Zsh，无需手动输入命令或重新连接 SSH。

**Architecture:** 保留安装器和菜单的现有分派，Zsh 启动仅放在变更完成、临时文件清理和锁释放之后。菜单的安装子进程不启动 Shell，由菜单记住成功的安装/修复操作，在退出菜单后统一进入；只读、卸载、在线自更新、失败、`--keep-shell`、非终端输入输出不启动。

**Tech Stack:** Bash、现有 as_user/runuser、Python unittest + PTY；不新增依赖。

## 行为设计

- `install`、`update`、`repair`、`component NAME install` 成功且共享 Zsh 配置和登录 Shell 均就绪时进入交互登录 Zsh。BBR 跳过/失败仍保留原退出码，不自动进入。
- stdin/stdout 都是终端时才启动；不从 `/dev/tty` 偷取管道、菜单或自动化输入。`--keep-shell` 同时保留登录 Shell 和当前会话。
- 使用既有 `as_user` 启动目标用户，显式设置 `SHELL` 为核验后的登录 Shell；不会在 sudo 提权后打开 root Shell。
- 启动前提示“正在进入用户的 Zsh，无需重新连接 SSH；输入 exit 返回原来的终端”；退出后提示“已返回原来的终端”。Shell 启动失败要单独说明，不能掩盖安装结果。
- `chsh` 成功后重新读取用户记录；仍为 Bash 或读取失败时报告安装失败。`status` 对非 Zsh 登录 Shell 返回 2，配置存在不能冒充 Shell 就绪。
- 直接入口与 bootstrap/已安装管理器复用同一安装器行为；菜单只在成功安装/修复后设置待进入状态，浏览、失败、卸载和 self-update 不设置该状态。

## 实施与验证

1. 在 `tests/test_shell_regressions.py` 新增切换失败/核验失败/成功/保持原 Shell 回归；新增 `tests/test_zsh_session.py` 覆盖真实 PTY 的直接安装、菜单退出、目标用户、提示、锁/清理、取消与非交互路径；扩展 `tests/test_status.py` 复现 Bash 状态误报。先运行新测试，确认失败。
2. 在 `modules/shell.sh` 添加启动辅助函数和切换核验；在 `install.sh` 的成功出口及菜单出口调用，先清理并释放锁；在 `modules/menu.sh` 记录安装成功和卸载清除状态。调整原 PTY 安装回归，让其退出新增的 Zsh 会话。
3. 更新 `README.md`、`agent.md` 和 `docs/verification.md` 的安装行为和验收记录。
4. 运行 `python3 -m unittest discover -s tests -v`、`bash tests/check.sh`、`git diff --check`。测试不修改真实账户、包、内核或 HOME；真实 Linux sudo/runuser 和 SSH 仍需服务器验收。

## 完成记录

已完成以上四步；全量 198 项测试通过，ShellCheck 0.9.0 和语法/空白检查通过。新增会话函数经 DEBUG 执行行跟踪覆盖 15/15；具体测试边界和服务器验收步骤见 `docs/verification.md` 的 2026-10-26 记录。未提交、未推送。
