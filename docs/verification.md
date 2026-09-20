# ShellReady 首版验证记录

日期：2026-09-20。当前为未发布的本地实现，不是已完成生产验收的发行版本。

## 已执行

| 检查 | 实际结果 |
| --- | --- |
| Python 标准库行为测试 | 36 项通过；系统写入、包安装与网络使用测试桩或临时目录 |
| Bash 语法检查 | install.sh、bootstrap.sh、lib、modules、tests 下的脚本通过 |
| Zsh 语法检查 | config/init.zsh 通过 |
| ShellCheck | v0.11.0，所有 Bash 脚本通过 |
| TOML 解析 | Starship 与 Atuin 配置可解析 |
| Git 空白检查 | git diff --check 通过 |
| 固定产物清单 | 9 个条目有固定版本/commit 和 SHA-256，无 latest 下载路径 |
| 实际上游下载抽查 | 6 个产物下载完成并与清单 SHA-256 匹配；详见下方 |

已下载核验：trzsz-go ARM64、Starship x86_64、Atuin ARM64、zoxide x86_64/ARM64、zsh-autosuggestions。还检查了已下载归档中的程序路径与安装器提取逻辑一致。

trzsz-go x86_64、Starship ARM64、Atuin x86_64 的本次额外下载核验因网络缓慢未完成。清单摘要来自官方发行 API；实际安装时仍会强制核验每个下载文件。ShellCheck 的 GitHub 下载超时后，使用工作目录中的 shellcheck-py 分发包运行了同版本检查器，没有向项目引入该运行时依赖。

测试覆盖以下行为：

- 未知参数、缺少参数、互斥操作及内核确认参数。
- 原配置保留、无末尾换行、重复接入、符号链接和损坏标记拒绝修改。
- 下载失败和摘要不符不会激活工具；工具安装重跑不覆盖原有同名程序。
- 配置文件原子写入、本地管理入口完整性。
- Zsh 在交互模式初始化一次、非交互脚本不加载增强、保留 cd 内建命令。
- Atuin 首次历史导入标记、保留用户自定义提示符配置。
- BBR 不支持时跳过、重复安装、应用失败恢复、恢复时拒绝覆盖后续修改。
- 内核 tag/架构/Max 拒绝策略、待重启状态、运行态 BBRv3 检查、拒绝卸载当前内核。

这里的“通过”只适用于测试覆盖的隔离行为。没有测量整体代码覆盖率，不据此宣称 80% 覆盖或内核安装端到端通过。

## 尚未执行

当前开发环境是 macOS，无 Docker 或 Linux VM：

- GitHub Actions 尚未触发（未提交、推送或发布）。
- 两种架构、四种 Linux 版本的真实 apt 安装与卸载尚未执行。
- 真实 root / sudo 用户环境的完整文件权限与登录 Shell 切换尚未验证。
- 真实 SSH 重连、trz/tsz 上传下载尚未验证。
- 默认 BBR 的真实系统写入与服务器重启后的持久性尚未验证。
- BBRv3 内核包安装、GRUB 启动、Secure Boot 检测与旧内核回退尚未验证。
- bootstrap.sh 的线上入口尚未发布，未做远程一键安装验收。

## 可复现本地检查

在仓库目录执行，需安装 Bash、Zsh、Python 3、ShellCheck：

```bash
python3 -m unittest discover -s tests -v
bash tests/check.sh
```

预期：所有测试通过，语法与静态检查无错误，git diff --check 无输出。

## Linux 容器验收

在具备 Docker 的测试机上，运行：

```bash
docker run --rm -v "$PWD:/src:ro" ubuntu:24.04 bash /src/tests/container-smoke.sh
```

脚本只允许在 Docker 容器内执行。对 ubuntu:22.04、debian:12、debian:13 及两种架构重复执行。CI 已配置对应矩阵。

预期：工具可运行、原配置保留、普通用户配置归属正确、重复安装无重复接入、卸载恢复原 Shell 并保留历史。此测试显式跳过 BBR，不能证明内核行为。

## 实机发布前验收

在有云控制台/救援入口的空白测试服务器上进行：

1. 执行 `bash install.sh --user 测试用户`，确认每个组件的结果；不支持 BBR 时应返回 2 并说明跳过。
2. 重新 SSH 登录，确认提示符、右键接受历史建议、Ctrl+R 搜索和 z 目录跳转。
3. 本地使用兼容 trzsz 的客户端，上传、下载同一测试文件，对比 SHA-256。
4. 记录 `uname -r` 和 `sysctl net.ipv4.tcp_congestion_control`，确认默认安装没有更换运行内核。
5. 在允许的测试窗口手动重启服务器，再检查 BBR 状态和工具配置。
6. 修改一行非项目管理的 .zshrc 内容，重跑并卸载，确认该行、历史和备份保留。
7. 单独验收 `uninstall --restore-bbr` 的恢复和冲突拒绝行为。
8. 在满足前置条件的另一个测试实例上选择标准 BBRv3 release，核验摘要后通过独立入口安装。先检查旧内核与引导文件，再手动重启，运行 status 验证。
9. 从云控制台选择旧内核启动，确认可回退，再测试 kernel-remove；必须拒绝卸载当前运行内核。

只有完成这些步骤并记录系统版本、架构、产物版本与实际输出，才应发布经过验证的安装入口。
