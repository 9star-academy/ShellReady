# 国内下载适配 Implementation Plan

**Goal:** 国内服务器无需配置网络代理即可通过公共或自定义镜像下载安装源码和固定工具。

**Architecture:** bootstrap.sh 保持可独立执行，同时提供无副作用的下载函数供 lib/common.sh 引用。auto 直连失败后切换镜像，cn 镜像优先，direct 仅上游；所有安装、更新和内核下载统一走此策略。cn 源码直接下载单份归档并读取 GitHub PAX commit 元数据，避免共享 API 限流；auto 的 commit API 失败时使用同一路径。固定 commit 下载和工具 SHA-256 校验保留。

**Tech Stack:** Bash、curl/wget、tar/gzip、现有 Python unittest；无新增运行依赖。

## 已确认约束
- 用户已确认 auto / cn / direct 模式及覆盖源码、工具、更新、可选内核。
- 默认 auto；README 国内命令显式设置 SHELLREADY_DOWNLOAD_MODE=cn。
- SHELLREADY_GITHUB_MIRROR 可指定 HTTPS 前缀；默认 https://gh-proxy.com。只对明确的 GitHub 域名进行镜像映射，Raw 文件优先使用固定版本 jsDelivr 地址，API 镜像失败时再尝试 https://gh-api.p3terx.com。
- 不修改系统 APT 源，不自动重启或改变内核安装的确认边界。
- 镜像是第三方信任边界；源码的 commit 标识不是独立签名证明。工具仍由仓库固定哈希校验。

## 执行步骤
1. tests/test_downloads.py、tests/test_bootstrap.py：先验证模式、镜像顺序、全直连失败、归档 commit、HTTP 拒绝、临时文件和校验失败；运行并确认新增行为测试失败。
2. bootstrap.sh：实现共享候选地址生成、有限超时/重试、原子下载及源码归档回退；lib/common.sh 的 download() 委托共享函数。
3. install.sh：显式通过 sudo env 传递已校验的两个下载配置；安装管理入口保存模式供后续更新使用，显式环境变量可以覆盖。
4. 更新 tests/test_self_update.py、安装/状态/菜单隔离夹具，确认安装后的管理入口携带下载策略且已有状态不变。
5. 运行 python3 -m unittest discover -s tests -q、bash/zsh 语法检查、ShellCheck、git diff --check。
6. 下载真实源码及两个架构的固定工具到临时目录核验 SHA-256，不执行远程工具；用本地源码调用独立入口 --help。更新 README、docs/verification.md，区分本机下载证据与国内实机验收。

## 验收
- GitHub 上游不可达时，镜像仍可完成源码、工具、更新下载；元数据与内核包使用同一下载策略。
- 错误模式/非 HTTPS 镜像在下载或提权前失败；下载失败不覆盖已存在的有效文件，校验失败不接入工具。
- cn 源码不调用 GitHub commit API；输出归档携带的 40 位 commit。auto/direct 正常路径继续解析一次 commit 并下载相同快照。
- 本机已存在的 202 项基线测试继续通过；国内服务器最终执行安装和 shellready status 验收。

## 实测依据
- GH-Proxy 的 commit API 返回 403，响应头为共享 API 配额耗尽；同服务的源码归档返回 200，归档首个全局 PAX 头含完整 commit。
- P3TERX API 缓存返回真实内核发行列表；新下载逻辑在 GH-Proxy 403 后成功回退并筛选标准 x86_64 tag。
- cn 模式真实获取源码，识别 commit `9003b5b8e44794675e9822c9d7d9577277d5bfbb` 并显示安装器帮助；未执行安装操作。
- config/assets.tsv 的全部九个固定文件均通过 cn 下载并匹配原 SHA-256（四类二进制工具 × 两种架构，另含补全插件）。
- 最终 224 项 Python 测试通过；ShellCheck 0.11.0 和 0.9.0 下 tests/check.sh 均通过。完整记录及国内验收命令见 docs/verification.md 的 2026-10-30 条目。
- 已完成实现及文档，未提交、未推送；国内 Linux 完整安装仍需服务器实测。
