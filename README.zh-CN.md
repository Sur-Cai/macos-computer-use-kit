<div align="center">

# macos-computer-use-kit

**给 AI agent 用的 macOS 电脑控制：AX 优先，MCP 服务器与 CLI 二合一。**
agent 读取辅助功能（Accessibility）树，不再靠截图猜坐标；输入在后台直接投递给目标应用，
你的光标不会移动；每个动作都做回读校验。

[English](README.md) · **简体中文**

[![PyPI](https://img.shields.io/pypi/v/macos-computer-use-kit?label=PyPI)](https://pypi.org/project/macos-computer-use-kit/)
[![Python](https://img.shields.io/pypi/pyversions/macos-computer-use-kit)](https://pypi.org/project/macos-computer-use-kit/)
[![pi package](https://img.shields.io/npm/v/pi-macos-computer-use?label=pi)](https://www.npmjs.com/package/pi-macos-computer-use)
[![dsh plugin](https://img.shields.io/npm/v/dsh-macos-computer-use?label=dsh)](https://www.npmjs.com/package/dsh-macos-computer-use)
[![CI](https://github.com/Sur-Cai/macos-computer-use-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/Sur-Cai/macos-computer-use-kit/actions/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-stdio-6f42c1)](https://modelcontextprotocol.io)
[![macOS 12+](https://img.shields.io/badge/macOS-12%2B-black?logo=apple)](#环境要求)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

</div>

```text
截图 → 猜坐标 → 点击 → 听天由命        ✗  慢、脆弱、还会抢你的鼠标
快照 → 按 #ref 操作 → 校验差异          ✓  本项目的做法
```

- **每个客户端一条命令接入。** 支持 Claude Code、Claude Desktop、Codex、Cursor、
  Gemini CLI、opencode、pi 和 DeepSeek Harness。stdio MCP 服务器，运行时只依赖
  pyobjc 和 Pillow。
- **辅助功能优先。** 每个元素都带稳定的 `#ref`、角色、标签和精确的屏幕坐标；再次观察时只返回
  差异。Electron / Chromium 应用会自动开启完整的辅助功能树。
- **后台输入。** 点击、按键、滚动、拖拽和 Unicode 输入都直接投递给目标进程，用户可以继续干活。
  中文、emoji、重音字符原样到达，剪贴板不受影响。
- **只认校验结果，不做乐观假设。** 每个结果都把 `action_sent`（事件已发出）和
  `verified`（界面确实变了）分开；失败时会说明可以 `retry`、需要 `reobserve`，还是 `never` 重试。
- **默认安全。** 内置密码管理器与系统认证的拒绝名单；密码框持有安全输入（Secure Event Input）
  时拒绝向其输入；安全字段一律脱敏；屏蔽锁屏、注销、强制退出等组合键。另有 dry-run 模式、
  只记录长度的审计日志，以及应用白名单 / 黑名单。
- **视觉只在必要时使用。** Set-of-mark 截图在可交互元素上画编号并关联 ref；Apple Vision
  端侧 OCR 返回屏幕坐标。两者都是针对画布、游戏和自绘界面的兜底方案。

## 目录

- [快速开始](#快速开始)
- [工具列表](#工具列表)
- [agent 应该怎么用](#agent-应该怎么用)
- [安全与隐私](#安全与隐私)
- [CLI 参考](#cli-参考)
- [其他 agent 集成](#其他-agent-集成)
- [Jev 语义护栏（可选）](#jev-语义护栏可选)
- [相关项目](#相关项目)
- [已知限制](#已知限制)
- [仓库结构](#仓库结构)

## 快速开始

### 环境要求

- macOS 12 及以上，Python 3.10 及以上。
- 给运行 agent 的应用（终端、Claude Desktop、Cursor 等）授予两项权限。
  `macos-cu doctor` 会明确告诉你哪个应用缺哪项权限。
  - **辅助功能**：读取辅助功能树、执行 AX 动作、投递输入都需要它。
  - **屏幕录制**：截图和 OCR 需要它（没有它，每一帧都是黑的）。

### Claude Code

二选一：

```bash
# A. 作为插件安装：MCP 服务器 + skill + /macos-doctor 命令
/plugin marketplace add Sur-Cai/macos-computer-use-kit
/plugin install macos-computer-use@macos-computer-use-kit

# B. 作为普通 MCP 服务器
claude mcp add --scope user macos-computer-use -- uvx macos-computer-use-kit mcp
```

插件会先在 `PATH` 里找 `macos-cu`，找不到就回退到 `uvx` 或 `pipx run`。
除了 [uv](https://docs.astral.sh/uv/) 或 pipx，不需要预装任何东西。

### 其他客户端，一条命令

```bash
pipx install macos-computer-use-kit          # 或：pip install / uv tool install
macos-cu setup claude-code                   # 还支持：claude-desktop、codex、cursor、gemini、opencode
macos-cu setup skill                         # 把 agent skill 复制到 Claude、Codex 和 opencode
macos-cu doctor                              # 权限、显示器、OCR、安全策略
```

`setup` 可重复执行，支持 `--dry-run`。JSON 配置采用合并写入，你已有的其他服务器会被保留；
首次修改前会写一份 `.bak` 备份。`--read-only` 只注册观察类工具。

<details>
<summary>手动配置 MCP（任意客户端）</summary>

```json
{
  "mcpServers": {
    "macos-computer-use": {
      "command": "uvx",
      "args": ["macos-computer-use-kit", "mcp"]
    }
  }
}
```

Codex（`~/.codex/config.toml`）：

```toml
[mcp_servers.macos-computer-use]
command = "uvx"
args = ["macos-computer-use-kit", "mcp"]
```

图形界面应用不会继承 shell 的 `PATH`。如果客户端找不到命令，请改用绝对路径（`which uvx`）。
`macos-cu setup print` 会打印适用于你这台机器的完整命令。

</details>

## 工具列表

MCP 服务器提供 18 个工具。观察类工具带 `readOnlyHint`，客户端可以自动放行。
想精简工具列表，可用 `mcp --read-only`、`--tools a,b` 或 `--exclude-tools c`。

| 工具 | 作用 |
| --- | --- |
| `macos_doctor` | 权限、显示器布局（点坐标、Retina 缩放、负坐标原点）、OCR、安全策略 |
| `macos_snapshot` | 以 `#ref 角色 尺寸 @screen[x,y] 标签` 列出可交互元素，按字符预算裁剪；`diff_against` 只返回变化 |
| `macos_find` / `macos_element_at` | 按角色或标题查找并返回精确坐标 / 命中测试某个屏幕点 |
| `macos_act` | 按 ref 操作元素：`press`、`set_value`、`focus`，或元素声明的任意动作（`AXShowMenu`、`AXIncrement` 等），带回读校验 |
| `macos_click` | 后台点击：左 / 右 / 中键，双击 / 三击，可带修饰键；`expect` 在窗口移动后拒绝执行 |
| `macos_type` / `macos_key` | Unicode 输入（中文、emoji 安全）或剪贴板安全粘贴 / 按键与组合键（`cmd+shift+t`、`mod+s`） |
| `macos_scroll` / `macos_drag` / `macos_hover` | 投递给目标进程的指针手势 |
| `macos_app` / `macos_window` / `macos_menu` | 启动、激活、退出应用或打开 URL / 文件 / 移动、缩放、最小化、置顶、关闭窗口 / 按路径操作菜单栏（`文件 > 导出…`） |
| `macos_screenshot` | 截取应用、窗口、区域或整个显示器，带空白帧检测；`annotate=true` 加 set-of-mark 编号 |
| `macos_ocr` | Apple Vision OCR，返回屏幕矩形；传 `text=` 只返回匹配项，可直接点击 |
| `macos_wait` | 等待元素出现、消失或值满足条件，替代 sleep |
| `macos_jev_guard` | 可选：不可逆操作前的语义校验（见 [Jev](#jev-语义护栏可选)） |

## agent 应该怎么用

```text
macos_doctor                                   只需一次：权限 + 显示器布局
macos_snapshot app="Notes"                     → #a1b2c3d4 AXButton 28x28 @screen[812,64] 新建备忘录 …
macos_act ref="a1b2c3d4"                       → {"ok":true,"action_sent":true,"verified":true}
macos_type app="Notes" text="周会纪要 ✅"        → Unicode 事件，剪贴板不受影响
macos_snapshot app="Notes" diff_against=<路径>  → 只返回变化的部分
```

这个循环背后的规则（随附的 [skill](skill/SKILL.md) 会教给 agent）：

1. **语义化观察。** 先快照，再截图。
2. **操作元素，而不是像素。** 优先用菜单路径和 AX 动作，其次在 `center_screen` 点击，最后才用快捷键。
3. **校验，而不是等待。** 用快照差异或 `macos_wait`。
4. **绝不盲目重试。** 如果 `action_sent` 为 true，在重复任何不能安全执行两次的操作前先重新观察。
   第二次点“发送”就是第二条消息。
5. **`stale_ref` 的意思是重新观察**，绝不是“挑一个最近的元素”。

### 坐标系

| 坐标系 | 含义 | 使用者 |
| --- | --- | --- |
| `screen[x, y]` | 全局点坐标，原点在主显示器左上角（与 AX、CGEvent 一致） | `macos_click`、`input --x --y`、`overlay` |
| 窗口相对坐标 | 元素坐标减去窗口原点 | `macos_click window_id=…` |
| 图片像素 | 截图像素 = 点坐标 × `backing_scale`（Retina 为 2） | 只在你自己读 PNG 时使用 |

位于主显示器左侧或上方的副屏，坐标会是**负数**，这是正常的；`macos_doctor` 会打印布局。

## 安全与隐私

一切都在本地运行，不发起任何网络请求。唯一的例外是可选的 Jev 护栏，只有在你配置了 key
并主动调用时才会联网。

| 防护 | 行为 | 覆盖方式 |
| --- | --- | --- |
| 敏感应用 | 密码管理器、钥匙串访问、“密码”应用、SecurityAgent、登录窗口和系统认证弹窗一律拒绝输入 | `MACOS_CU_ALLOW_SENSITIVE=1` |
| 安全输入 | 目标应用的密码框持有 Secure Event Input 时拒绝输入；安全字段的值在所有树和结果中都会脱敏 | — |
| 锁屏 | 屏幕锁定时拒绝一切输入 | — |
| 系统组合键 | 拒绝锁屏、注销、强制退出 | `MACOS_CU_ALLOW_SYSTEM_CHORDS=1` |
| 应用白 / 黑名单 | 只允许 / 永不允许这些 bundle id 或名称 | `MACOS_CU_ALLOW_APPS`、`MACOS_CU_DENY_APPS` |
| Dry run | 解析目标并报告，但不投递任何事件 | `MACOS_CU_DRY_RUN=1` |
| 审计日志 | 每个改动类动作记一行 JSON；输入的文本**只记录长度** | `MACOS_CU_AUDIT=1` |

本地文件只对你的账户可见：

- 快照缓存和审计日志位于 `~/.cache/macos-computer-use/`，或 `MACOS_CU_CACHE_DIR` 指定的目录。
- 创建时权限为 `0700` / `0600`。
- 快照只保留最新的 20 份（`MACOS_CU_SNAPSHOT_KEEP`）。
- 截图和 OCR 图像只写到你指定的位置（`out=`），OCR 的临时截图用完即删。

## CLI 参考

每条命令都输出 JSON（`ax tree/find/snapshot` 输出紧凑文本），任何 shell 都能驱动。
退出码是稳定的：`0` 成功，`2` 用法或权限问题，`3` 未找到 / ref 失效，`4` 截图失败，
`5` 目标已变化，`6` 被安全策略拒绝，`7` 超时。

| 命令组 | 子命令 |
| --- | --- |
| `macos-cu ax` | `snapshot`（`--interactive`、`--budget`、`--diff`）、`find`、`tree`、`at`、`actions`、`press`、`setvalue`、`focus`、`action --name`、`wait`、`resolve` |
| `macos-cu input` | `click`（`--button`、`--count`、`--flags`）、`type`、`key`（组合键）、`scroll`、`drag`、`hover`、`move`、`windows`、`cursor`、`pid` |
| `macos-cu paste` | 剪贴板安全粘贴：确认应用确实读取了内容，并恢复原剪贴板 |
| `macos-cu app` | `list`、`launch`、`activate`、`hide`、`quit`、`open --target URL/文件` |
| `macos-cu window` | `list`、`move`、`resize`、`minimize`、`restore`、`raise`、`focus`、`close`、`fullscreen` |
| `macos-cu menu` | `list`、`select --path "文件 > 导出…"` |
| `macos-cu shot` | `capture`、`annotate`、`check`、`windows`、`displays` |
| `macos-cu ocr` | 对应用、窗口、区域或文件做 Vision OCR（`--text`、`--lang zh-Hans,en-US`） |
| `macos-cu mcp` / `setup` / `doctor` | 启动 MCP / 注册到客户端 / 诊断 |
| `macos-cu overlay` / `jev` | 可视反馈圈 / 可选语义护栏 |

```bash
macos-cu ax snapshot --app Finder --interactive
macos-cu ax press --app Finder --ref 9d2261d7
macos-cu menu select --app Safari --path "文件 > 新建无痕窗口"
macos-cu input type --app Notes --text "你好, world 👋"
macos-cu input click --window-id 12345 --x 171 --y 28 --expect "<pid:wid:x:y:w:h>"
macos-cu shot annotate --app "System Settings" --out /tmp/marks.png
macos-cu ocr --app Preview --text "合计"
```

## 其他 agent 集成

MCP 服务器已覆盖大多数客户端。另外为两个偏好自有工具格式的框架提供了原生桥接，
二者都是同一个 CLI 的薄封装，以 argv 数组调用（`shell: false`）。

| 框架 | 包 | 安装 |
| --- | --- | --- |
| [pi](https://pi.dev) | [`pi-macos-computer-use`](https://www.npmjs.com/package/pi-macos-computer-use)：skill + 16 个工具 | `pi install npm:pi-macos-computer-use` |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | [`dsh-macos-computer-use`](https://www.npmjs.com/package/dsh-macos-computer-use)：Cordis bundle，11 个工具 | `dsh plugin --profile <名称> add dsh-macos-computer-use` |
| opencode | skill + MCP 配置 | `macos-cu setup opencode`（或在 checkout 里执行 `./install.sh`） |

请先安装 CLI（`pipx install macos-computer-use-kit`）。如果从 Dock 启动的应用找不到它，
设置 `MACOS_CU_BIN=/绝对路径/macos-cu`。所有产物共用一个版本号、同步发布。
详见 [`packages/pi`](packages/pi/README.md) 和 [`packages/dsh`](packages/dsh/README.md)。

## Jev 语义护栏（可选）

这是唯一需要 key 的功能。在不可逆操作之前，一个小模型给出校准过的判断：
*这还是目标收件人吗？输入框里是预期的内容吗？有什么阻碍这个操作？*
是否继续由**代码**决定，模型最多只能建议两种不会发出任何东西的恢复动作。

```bash
echo '{"task":"把报告发给 Alice",
       "expected":{"recipient":"Alice","message":"Q3 数据"},
       "observed":{"chat_title":"Bob","input_text":"Q3 数据"}}' | macos-cu jev guard
# {"answers":{"right_target":0.02,"input_ok":0.98,"blocker":"wrong_target"},"decision":"switch_target"}
```

key 从 `TYPESAFE_API_KEY` 或 `~/.config/typesafe/api_key` 读取
（<https://console.typesafe.ai/keys>）。问题设计指南见
[`skill/reference/jev-best-practices.md`](skill/reference/jev-best-practices.md)。

## 相关项目

电脑控制是个热闹的领域，下面这些项目值得了解（star 数截至 2026 年 9 月），按需选择。

| 项目 | 平台 · 语言 | 适合你想要… |
| --- | --- | --- |
| [trycua/cua](https://github.com/trycua/cua) ★26k | macOS/Linux/Windows · Swift/Rust/Py | 虚拟机沙箱（Lume）、驱动 + 基准测试、跨平台 agent |
| [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) ★39k | 跨平台 · TS | 由视觉模型驱动的桌面 agent 应用 |
| [microsoft/OmniParser](https://github.com/microsoft/OmniParser) ★25k | 任意 · Py | 截图 → UI 元素，适合纯视觉 agent |
| [microsoft/UFO](https://github.com/microsoft/UFO) ★10k | Windows · Py | 基于 Windows UI Automation 的 agent 系统 |
| [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP) ★7k | Windows · Py | 本项目的 Windows 对应物 |
| [openclaw/Peekaboo](https://github.com/openclaw/Peekaboo) ★5k | macOS · Swift | 原生 Swift CLI + 菜单栏应用，带标注截图 |
| [iFurySt/open-codex-computer-use](https://github.com/iFurySt/open-codex-computer-use) ★2k | macOS/Linux/Windows · Swift | Codex 电脑控制工具面的开源复刻 |
| [ghostwright/ghost-os](https://github.com/ghostwright/ghost-os) ★2k | macOS · Swift | AX 优先的 MCP，带“演示即学习”录制器 |
| [lahfir/agent-desktop](https://github.com/lahfir/agent-desktop) ★2k | macOS · Rust | 采用“先骨架后下钻”遍历的 AX CLI |

**本项目的定位。** 纯 Python + pyobjc，没有需要公证的二进制，`uvx` 随处可跑。
重点是 agent 循环的可靠性：带重试语义的校验结果、失效 ref 检测、快照差异，以及确定性的安全策略；
可选的 Jev 护栏在不可逆操作前再加一道校准过的检查。设计上借鉴了成熟电脑控制 agent
共同收敛出的模式，并从零重新实现。

## 已知限制

- 仅支持 macOS。AX、CGEvent、ScreenCaptureKit、Vision 都是 macOS 专有 API。
- 自绘界面（游戏、画布、部分聊天应用）几乎不暴露辅助功能数据。这类场景请用 `annotate`、`ocr`
  和坐标点击，并做视觉校验。
- 大多数应用接受后台输入，但少数应用只有在前台时才接受输入或粘贴。请先调用
  `macos_app action=activate`。
- 用户可能同时在操作电脑。在不可逆操作前多做一次校验，成本很低。

## 仓库结构

```text
src/macos_computer_use/   CLI + MCP 服务器（唯一实现来源）
skill/                    agent skill（规范版本，由 scripts/sync-skill.sh 同步到各包）
plugins/claude-code/      Claude Code 插件（MCP 启动器、skill、/macos-doctor）
.claude-plugin/           供 `/plugin marketplace add` 使用的 marketplace 清单
packages/pi/              pi 包（skill + 原生工具）
packages/dsh/             DeepSeek Harness bundle
tests/                    单元测试：安全策略、组合键、差异、OCR 几何、MCP 协议
tools/*.py                旧版脚本入口，调用同一套模块
```

约定见 [CONTRIBUTING.md](CONTRIBUTING.md)，发布流程见 [PUBLISHING.md](PUBLISHING.md)，
变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE)
