# ShellReady

**新服务器，一键配顺手。**

一条命令配好 Linux 服务器，集成 BBR、trzsz-go、Starship、zsh-autosuggestions、Atuin 和 zoxide，让每次 SSH 登录都更顺手。

> 当前为首版实现，尚未发布正式版本。已提供本地安装入口、状态检查、卸载和可选 BBRv3 内核升级；Linux 整机安装、SSH 传输与内核启动仍需验收。测试记录见 [验证说明](docs/verification.md)。

## 功能

| 组件 | 安装内容 | 日常使用 |
| --- | --- | --- |
| [BBR](https://github.com/google/bbr) | 启用当前内核的 BBR 并保存配置 | 默认不换内核、不要求重启 |
| [trzsz-go](https://github.com/trzsz/trzsz-go) | Go 版 trz / tsz | trz 上传、tsz 下载 |
| [Starship](https://starship.rs/) | Rust 版提示符，使用普通字符 | 显示用户、主机、目录、Git 与命令耗时 |
| [zsh-autosuggestions](https://github.com/zsh-users/zsh-autosuggestions) | Zsh 历史命令建议 | 输入前缀，按右方向键接受建议 |
| [Atuin](https://github.com/atuinsh/atuin) | 本机命令历史与搜索 | Ctrl+R 搜索历史，保留原方向键行为 |
| [zoxide](https://github.com/ajeetdsouza/zoxide) | 智能目录跳转 | 访问目录后，使用 z 关键词跳转 |

包含 Zsh、补全和持久配置，默认将目标用户的登录 Shell 设置为 `/bin/zsh`。可以通过 `--keep-shell` 保留原登录 Shell，再手动运行 `zsh`。已有 Oh My Zsh 等配置会保留，但其快捷键和提示符可能与本项目配置互相覆盖，应在测试环境检查。

工具使用官方预编译程序，不要求服务器安装 Go 或 Rust。固定版本与 SHA-256 见 [产物清单](config/assets.tsv)：trzsz-go 1.2.0、Starship 1.26.0、zsh-autosuggestions 0.7.1、Atuin 18.22.0、zoxide 0.10.0。

## 环境范围

以下是安装器当前允许的范围，不等于已经完成各环境的实机认证。

| 项目 | 要求 |
| --- | --- |
| 系统 | Ubuntu 22.04 / 24.04，Debian 12 / 13 |
| 架构 | x86_64 / ARM64（aarch64） |
| 权限 | 安装和卸载需要 root 或 sudo；status 可由目标用户只读执行 |
| 网络 | 可访问发行版 apt 源、GitHub 及其下载域名 |
| 配置目录 | 标准 HOME 和 `.zshrc`；自定义 ZDOTDIR 或符号链接 `.zshrc` 会拒绝自动接入 |
| 容器 | 可用 `--skip-bbr` 测试工具；容器不支持本项目的内核升级 |

脚本使用独立目录保存工具，不替换系统中已有的同名程序。进入配置后的 Zsh 时，ShellReady 的工具目录优先于原 PATH。

## 本地安装

把完整仓库放到目标 Linux 服务器，在仓库目录执行：

```bash
bash install.sh
```

普通用户执行时会按需调用 sudo，并为原用户配置。以 root 为其他用户安装时，明确指定用户：

```bash
bash install.sh --user ubuntu
```

常用选项：

```bash
bash install.sh --keep-shell
bash install.sh --skip-bbr
bash install.sh --help
```

安装后重新连接 SSH。使用 `--keep-shell` 时，手动运行 `zsh` 后才会加载这些增强功能。默认 BBR 操作不要求重启整台服务器。

### 远程一条命令入口

仓库包含 `bootstrap.sh`：先解析一个仓库 commit，再下载该 commit 的完整源码，避免入口和模块版本不一致。下载失败时不会继续执行。

**当前工作区代码尚未推送，不能直接使用 GitHub 下载入口。**发布并验证后，可将 `bootstrap.sh` 下载到服务器再用 Bash 执行；通过 `SHELLREADY_REF` 指定 tag 或 commit，默认使用 main。本地维护命令不依赖重新下载入口。

## 状态、修复与卸载

安装并进入配置后的 Zsh 后，可使用本地命令：

```bash
shellready status
shellready update
shellready uninstall
```

也可以在完整仓库目录执行 `bash install.sh status`、`bash install.sh update`、`bash install.sh uninstall`。

- `status`：显示工具版本、Shell 接入段、当前 BBR 和项目内核状态。交互和网络体验仍需实际验证。
- `update`：按当前安装器携带的固定清单重新安装或补齐配置，不自动拉取上游 latest。升级清单需使用新版仓库或引导入口。
- `uninstall`：移除本项目工具与 `.zshrc` 接入段；若登录 Shell 仍是项目设置的 `/bin/zsh`，恢复原 Shell。保留历史数据、备份、系统依赖及内核。

BBR 是全机设置，普通卸载保留它。需要恢复本项目安装前的 TCP 算法时，显式执行：

```bash
shellready uninstall --restore-bbr
```

如有其他用户正在使用该全机 BBR 配置，应先协调。配置或算法被后续操作修改时，恢复会停止并提示，避免覆盖新设置。已卸载本地命令后，可用仓库入口继续恢复。

退出码：`0` 成功；`1` 失败；`2` 部分跳过或尚未就绪。工具下载失败时不接入不完整的 Shell 配置，修复后重跑即可继续。

## BBR 与可选 BBRv3

### 默认：启用当前内核 BBR

检测并按需加载 `tcp_bbr`，启用已有能力，写入独立 sysctl 配置。不支持时明确跳过，不阻断其他工具；不更换内核，也不替换现有网卡 qdisc 或附加激进网络参数。

算法名为 `bbr` 本身不能证明是 v3，BBR 的实际收益取决于链路。

### 可选：安装指定 BBRv3 内核

独立入口使用 [byJoey/Actions-bbr-v3 Releases](https://github.com/byJoey/Actions-bbr-v3/releases) 的**标准版**内核，要求明确指定 release tag。先检查系统、架构、容器环境、GRUB、当前内核回退文件、磁盘空间和 UEFI Secure Boot 状态。

当前允许 Ubuntu 24.04、Debian 12/13，要求 `update-grub`、`systemd-detect-virt`，以及 `/boot` 所在分区至少 1 GiB 可用空间。UEFI 环境还需 `mokutil`，且必须确认 Secure Boot 关闭。其他引导方式不自动处理。

在 Releases 页面选择与服务器架构对应的标准 tag 后执行（占位符需要替换）：

```bash
shellready bbrv3 --tag '<标准版 release tag>' --yes
```

该入口核验 GitHub API 提供的 SHA-256、内核包名、版本和架构，仅安装匹配的 `linux-image` 包，不安装 headers、libc-dev、Max 内核，不删除旧内核。上游产物结构不符合要求时会拒绝安装。

成功后显示“已安装，待重启验证”，退出码为 `2`。重启指**重启整台服务器**，会断开 SSH 并暂时中断业务；何时重启由用户决定，脚本不自动执行。重启前确认云厂商控制台或救援入口可用。重新连接后执行 `shellready status`，检查运行内核、已加载模块版本和拥塞控制算法。

卸载由 ShellReady 记录的内核前，必须先启动其他可用内核：

```bash
shellready kernel-remove --tag '<已安装的标准版 release tag>' --yes
```

正在运行的内核会被拒绝卸载。此功能尚未完成真实服务器启动与回退验收，不应直接用于承载业务的服务器。

## 文件传输与本地历史

服务器端提供 `trz` / `tsz`。本地需要支持 trzsz 的终端，或使用 `tssh`、`trzsz ssh` 连接；仅安装服务器工具不会自动给普通 SSH 增加上传交互。详见 [trzsz-go 使用说明](https://github.com/trzsz/trzsz-go#usage)。

Atuin 使用本项目独立配置，默认关闭自动同步和更新检查，不自动注册、登录或上传历史。首次安装尝试导入目标用户已有的标准 Bash/Zsh 历史文件，成功后记录标记；当前仍在其他会话内、尚未写入历史文件的命令不会被导入。

## 文件位置

| 路径 | 内容 |
| --- | --- |
| `~/.local/share/shellready/` | 专属工具、管理命令、固定产物清单与配置 |
| `~/.local/share/shellready/config/starship.toml` | 可自行调整的提示符，重跑保留 |
| `~/.local/share/shellready/config/atuin/config.toml` | 本项目 Atuin 配置，重跑保留 |
| `~/.local/state/shellready/` | 原 Shell、导入标记和 `.zshrc` 备份，卸载保留 |
| `~/.zshrc` | 追加可识别的 ShellReady 接入段，其他内容保留 |
| `/etc/sysctl.d/90-shellready-bbr.conf` | 项目 BBR 持久配置 |
| `/var/lib/shellready/bbr/` | 全机 BBR 原状态与配置摘要 |
| `/var/lib/shellready/kernels/` | 可选内核安装与验证记录 |

历史数据存放在各工具的数据目录中，不在 ShellReady 工具目录内；卸载不会删除它们。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
bash tests/check.sh
```

`tests/check.sh` 需要 Bash、Zsh 和 ShellCheck。`.github/workflows/ci.yml` 配置了两种架构、四个系统版本的容器安装测试；容器测试显式跳过 BBR，不代替真实内核、重启或 SSH 传输验证。

项目目标见 [agent.md](agent.md)，实现步骤见 [开发计划](docs/plans/2026-09-20-shellready-v0.1.md)，实际测试边界见 [验证记录](docs/verification.md)。

## 参考与致谢

参考 [byJoey/Actions-bbr-v3](https://github.com/byJoey/Actions-bbr-v3) 的环境说明、版本选择、状态检查和卸载组织方式。ShellReady 独立实现管理逻辑，不直接执行上游安装脚本；可选内核功能使用其发行产物。

感谢 BBR、trzsz-go、Starship、zsh-autosuggestions、Atuin、zoxide 和 Zsh 的维护者。各上游组件遵循各自许可证；ShellReady 的项目许可证待维护者确定。
