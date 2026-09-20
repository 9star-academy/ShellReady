# ShellReady v0.1 Implementation Plan

**Goal:** 实现可复用的一键安装、检查、恢复工具，默认使用现有 BBR，可选安装指定 BBRv3 内核。

**Architecture:** Bash 入口调度独立模块。工具装入目标用户专属目录；用户配置使用受管理的接入段，系统 BBR 使用独立配置文件。远程引导先解析仓库 commit，再下载同一 commit 的完整安装器。

**Tech Stack:** Bash、apt、curl/wget、SHA-256、Python 标准库测试、GitHub Actions。

用户已要求直接在当前仓库实现。本次不创建工作树、不提交、不推送，计划在本会话顺序执行。

## 1. 测试先行

创建 tests/test_shellready.py：隔离临时目录测试安装入口、参数验证、配置接入与卸载、校验失败、BBR 跳过与回退。
运行 `python3 -m unittest discover -s tests -v`，先确认缺少实现失败，再实现。

## 2. 入口与公共能力

创建 install.sh、bootstrap.sh、lib/common.sh、config/assets.tsv。
实现 root/sudo 与目标用户解析、系统检查、独立临时目录、固定产物校验、并发锁、参数验证。
安装器测试不允许修改真实系统；系统写操作通过测试桩替换。

## 3. 工具与 Shell

创建 modules/tools.sh、modules/shell.sh、config/init.zsh、config/starship.toml、config/atuin/config.toml。
一次安装 trzsz-go、Starship、Atuin、zoxide、zsh-autosuggestions，添加独立接入段，保存原 Shell，支持 --keep-shell。
采用目标用户 ~/.local/share/shellready 和 ~/.local/state/shellready；工具使用发行版本+摘要目录保证更新可重试。
保留用户原工具、配置、历史数据；不自动注册账号或联网同步。

## 4. BBR 与可选内核

创建 modules/bbr.sh、modules/kernel.sh。
默认只配置 tcp_congestion_control，保留现有 qdisc；不把 FQ 全局替换和激进调优纳入默认安装。
BBR 不支持返回跳过状态；系统配置与运行态有独立快照及冲突检查。
可选内核使用 byJoey/Actions-bbr-v3 指定 release 的 image 包，校验 API digest、架构、包名、引导条件；不删除内核，不重启。

## 5. 状态、卸载与 CI

检查工具版本、接入段、配置、BBR 与待重启内核。
卸载仅移除专属安装目录、接入段，恢复本工具改动且未被后来修改的 BBR/Shell；保留历史与备份。可选内核卸载拒绝当前运行内核。
创建 .github/workflows/ci.yml，执行 Bash 语法、ShellCheck、Python 测试与 Debian/Ubuntu 容器安装冒烟测试。

## 6. 文档与验收

更新 README.md、agent.md、docs/verification.md，准确列出实现、测试边界、命令和来源。
运行 `python3 -m unittest discover -s tests -v`、`bash -n`、ShellCheck、`git diff --check`。
真实服务器的 SSH、上传下载、内核启动与回退列为发布前验收，未执行不可写成通过。
