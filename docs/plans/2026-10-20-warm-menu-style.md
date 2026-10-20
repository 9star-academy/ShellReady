# B2 Warm Menu Style Implementation Plan

**Goal:** 总菜单和 BBR 子菜单采用用户选定的 B2 焦糖暖夜、暖黄主色和奶油白高亮，保留旧一键安装，不提交。

**Architecture:** 在 modules/menu.sh 中共享菜单主题、布局和选择器。TTY 支持数字、上下方向键和 Enter；管道、NO_COLOR、dumb 或小终端保留逐行数字输入。颜色逐行复位，不更改终端主题；操作仍通过原独立 CLI 分派，确认规则不变。安装和启停状态只读取文件与 sysctl，不启动工具、不安装依赖或探测远程 API。

**Tech Stack:** 现有 Bash、Python unittest / 标准库 PTY；无新增依赖。

## Task 1: 行为回归

- 修改 tests/test_menu.py 的隔离环境以加载真实组件只读函数。
- 新建 tests/test_menu_style.py：先复现缺少主题/选中、键盘操作和真实状态展示的失败。
- 用 PTY 覆盖两级菜单、数字 10、方向键、退格、确认取消、EOF 和终端恢复；覆盖无颜色/小终端降级及只读状态。
- 运行 `python3 -m unittest discover -s tests -p 'test_menu*.py' -v`。

## Task 2: 菜单实现

- 修改 modules/menu.sh：共享 B2 颜色、分隔线、状态列、窄屏文字裁剪、菜单区域重绘和无颜色降级。
- 总菜单默认高亮退出，BBR 默认高亮返回；Enter 前不执行操作。渲染与键盘读入不持有锁，不安装任何依赖。
- 只读状态：组件收据/入口/停用标记、当前 TCP 算法、默认队列、已加载 BBR 模块版本和运行内核；实际出口队列仍由原“查看状态”操作检查。
- 保留原 action/case、危险操作的 y/N 确认，以及 install.sh/bootstrap.sh 默认安装行为。

## Task 3: 验证与交付

- 运行 `python3 -m unittest discover -s tests -v`、`bash tests/check.sh`、`git diff --check`。
- 用真实菜单输出核对两级布局与颜色；PTY 验证只覆盖本地终端，真实 SSH、Linux 包安装及内核流程不作已验证声明。
- 更新 README.md、agent.md 和 docs/verification.md，说明操作、降级和未发布边界。
- 在当前有既有未提交工作的工作区增量修改；不暂存、不提交、不推送。

## 执行结果

- 总菜单与 BBR 子菜单的 B2 风格、真实状态列、数字/方向键高亮及降级已完成，原安装和变更确认行为保留。
- 先复现并修复旧 Bash 中文字宽错位、缩小窗口后丢失已输入选项的问题；两种 locale 均通过显示宽度检查。
- 145 项本地测试全部通过，Bash/Zsh 语法、ShellCheck 和空白检查通过；实际 ANSI 输出已绘图检查。
- README、agent.md 与 docs/verification.md 已更新；未暂存、未提交、未推送。真实 Linux SSH、安装和内核验收仍待执行。

## 整体复查

- 按用户要求继续审查美化、方向键与原一键安装，不提交。
- 补充可见屏幕与控制 PTY 测试，先复现退格残影、箭头后数字拼接、特殊按键残留、长输入折行、小窗口编辑及中断后的终端模式问题，再增量修复。
- 状态列改为检查当前入口权限，避免完整旧副本掩盖当前入口损坏。
- 新增真实彩色 PTY 下的默认/显式安装及 bootstrap 参数转发回归；本轮三个入口/复制清单文件校验值未变化。
- 156 项测试与静态检查通过；修复明细、证据及实机限制见 docs/verification.md。

## 作者署名

- 用户确认在顶部系统信息下方新增作者 tangbaichuan 与 https://github.com/reedtang666，总菜单和 BBR 子菜单统一展示，不提交代码。
- 复用当前主题、字宽计算和行数计数；正常窗口单行展示，窄窗口分成作者/地址两行，菜单行为与安装入口保持不变。
- 补充最小交互窗口重绘、窄窗口完整地址及纯文本输出回归，执行完整测试与静态检查。
