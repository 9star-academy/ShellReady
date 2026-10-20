# ShellReady Management Menus Implementation Plan

**Goal:** 保留原一键安装，增加总菜单、五个工具独立管理与 BBR 子菜单，所有修改留在本地。

**Architecture:** install.sh 保持现有默认和非交互命令，新增 menu、组件操作和 BBR 操作。menu.sh 只读取选择并分派独立 CLI 子进程；组件共享已有安装与 Shell 接入，禁用状态不执行为代码。BBR 队列管理独立记录、验证和恢复，内核版本列表复用上游固定来源。

**Tech Stack:** Bash、Zsh、Python unittest、现有 curl / jq / iproute2 系统命令；不引入框架。

## Task 1: 菜单与组件测试
- 新建 tests/test_menu.py、tests/test_components.py；覆盖旧默认、已安装管理入口、返回/退出/EOF/无效输入、取消变更、失败后返回、组件隔离与禁用状态。
- 运行新增测试确认未实现失败，再实现 modules/menu.sh、modules/components.sh、install.sh 分派、config/init.zsh 和复制清单。
- 工具停用保持数据，单项修复不安装其他工具；修复菜单仅修复已有组件。

## Task 2: BBR 功能
- 新建 BBR 队列回归测试，先复现缺少功能，再实现 FQ 主动设置、冲突保留、恢复与部分失败清理。
- modules/kernel.sh 增加标准版本列表，过滤架构/预发布/Max，下载错误不进入安装。
- BBR 菜单仅在明确选择后变更，安装内核仍需要明确 tag 与确认，移除仍检查运行内核。

## Task 3: 验证与文档
- 运行 python3 -m unittest discover -s tests -v 和 bash tests/check.sh，修复真实失败。
- 更新 README.md、agent.md、docs/verification.md，提供旧一键安装、menu 入口和实际验收步骤。
- 核验 git diff --check、帮助和工作区状态。不提交、不推送；真实网卡、重启与 SSH 交互单独标注待验收。

## 执行结果（2026-10-20）

- 总菜单、组件独立操作和 BBR 子菜单完成；保留旧一键安装入口及原非交互命令。
- 新增 45 项行为测试，总计 123 项通过；静态检查、帮助与 diff 检查通过。
- 新的条件调用路径显式传播产物下载、摘要、写入和安装失败，避免失败后继续接入 Shell。
- 完整实现与验收边界见 README.md、docs/verification.md。临时计划笔记已合并至本计划和验证记录。
- 未提交、未推送、未部署；真实 Linux、SSH、FQ 和内核启动/回退仍待验收。

## 整体复查（2026-10-20）

- 根据用户要求复查三种入口的组合行为，不提交。
- 新增失败用例复现并修复共享 Shell 初始化时序、FQ 状态遗漏、单项依赖失败传播、BBR 持久化失败误报。
- 新增真实模块的连续入口切换回归，测试共 133 项通过；静态检查通过。
- 详细复现、修改和未验证边界已补入 docs/verification.md。
