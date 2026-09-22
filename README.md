# macos-computer-use-kit

给 AI agent 用的 **macOS 电脑控制工具箱**：语义定位（AX）、进程级输入、剪贴板安全、
动作回读校验、视觉反馈，以及可选的 Jev（TypeSafe System One）语义护栏。

> A small, composable toolkit for driving macOS UIs from an AI agent: accessibility-tree
> targeting, process-scoped input, clipboard-safe pasting, action read-back verification,
> visual feedback, and optional LLM-free semantic guards via Jev.

这些工具是从三个成熟实现里提炼出来的做法，而不是从零发明：

| 灵感来源 | 吸收的机制 |
| --- | --- |
| Codex CUA（`@oai/cua` / Sky 服务） | AX 状态 + element index、`setValue`、批量动作、持久化会话 |
| ZCode（`ZCode Computer Use`） | `*_to_window` 窗口级输入、`target_changed` 校验、剪贴板安全粘贴管线、`screenshot_blank` |
| Grok Bot（`CUGrokBotService`） | 带稳定 element_id 的快照 + 文本预算 + 下钻、动作后回读、失败时降级到坐标 |

## 组件

| 文件 | 作用 | 关键能力 |
| --- | --- | --- |
| `tools/ax_tool.py` | 读取 macOS 辅助功能树 | `tree` / `find` / `snapshot --budget`（稳定 id + 省 token）/ `resolve` / `press` / `setvalue`（**带回读校验**） |
| `tools/assist.py` | 进程级输入（物理光标不动） | `windows` / `click|key|scroll --window-id N --x <窗口内相对坐标>` / `--expect` 目标签名校验 / `--show` 视觉反馈 |
| `tools/smart_paste.py` | 剪贴板安全粘贴 | 保存并恢复用户剪贴板、检测被他人抢占、返回 `action_sent` |
| `tools/shot.py` | 截图与**空白帧检测** | `capture --app X`（窗口级）/ `check --file` → `ok / all_black / all_white / uniform` |
| `tools/overlay.py` | 光圈 + 标签 overlay | 点击穿透、层级最高、自动淡出 |
| `tools/jev_select.py` | 从候选元素里语义选一个 | 带 `none` 逃生口 + 置信度门限 |
| `tools/guard.py` | **动作前语义护栏** | 一次调用 fan-out 4 个判断（目标/内容/阻塞/下一步），由代码按阈值决策 |
| `skill/` | opencode skill 文档 | 完整流程、避坑清单、Jev 最佳实践沉淀 |

## 快速开始

```bash
# 1) 依赖：macOS 12+，Python 3.10+（pyobjc / Pillow / mss）
pip install pyobjc-framework-Quartz pyobjc-framework-AppKit pyobjc-framework-ApplicationServices pillow

# 2) 授权：系统设置 → 隐私与安全性 → 辅助功能 / 屏幕录制（给运行这些脚本的进程）

# 3) 用法示例
V=python3
A=tools/ax_tool.py

# 语义定位：拿元素精确坐标（不靠截图目测）
$V $A find --app com.apple.finder --role AXButton --title 大小

# 带稳定 id 的快照（预算裁剪，省 token）
$V $A snapshot --app com.apple.finder --budget 1200

# AX 原生动作 + 回读校验（原生控件首选）
$V $A press --app com.apple.finder --role AXButton --title 大小
# {"verified":true,"state_changed":true,...}

# 窗口级输入（相对坐标 + 目标签名校验 + 视觉反馈）
$V tools/assist.py windows --app Finder
$V tools/assist.py click --window-id 12345 --x 171 --y 28 --show

# 剪贴板安全粘贴（保存/恢复用户剪贴板，检测抢占）
$V tools/smart_paste.py --app com.google.Chrome --text "hello" --mode pid

# 截图空白检测
$V tools/shot.py capture --app Finder --out /tmp/f.png
```

## 设计原则

1. **AX-first**：能用辅助功能树定位就不要截图目测。语义 + 精确几何，零视觉推理。
2. **动作发出 ≠ 动作生效**：`action_sent`（是否发出）与 `verified`（是否生效）分开报告。
   回读依据是"窗口可见文本指纹 + 焦点元素"的前后对比；未通过时给出降级建议。
3. **剪贴板是共享资源**：写入前保存、完成后恢复；检测"被用户抢占"与"目标未消费"。
4. **目标必须显式且可校验**：窗口级输入带签名 `pid:wid:x:y:w:h`，不匹配即 `target_changed`。
5. **不确定性交给小模型，控制权留给代码**：Jev 只做窄判断（身份/状态/效果/路由），
   阈值与副作用永远在代码里；成本阶梯 `确定性代码(µs) < Jev(~1s) < 视觉推理(秒~几十秒)`。
6. **让人看得见**：动作点画光圈，避免"黑盒操作"。

## Jev 集成（可选）

需要 `TYPESAFE_API_KEY`（环境变量或 `~/.config/typesafe/api_key`）。不需要 Jev 时其余工具完全可用。

```bash
# 动作前护栏：发消息/提交表单前跑一次
echo '{"task":"把分析发给联系人A",
       "expected":{"recipient":"联系人A","message":"…"},
       "observed":{"chat_title":"另一个会话","input_text":"…"}}' | python3 tools/guard.py
# → {"answers":{"right_target":0.06,"input_ok":0.93,"blocker":"wrong_target",...},
#    "decision":"switch_target"}
```

## 已知局限

- 仅 macOS（AX / CGEvent / ScreenCaptureKit 都是 macOS API）
- 自绘 UI 的 AX 支持有限：例如微信侧栏按钮不接受 `AXPress`（工具会正确判为未验证并建议坐标点击）
- 坐标换算依赖显示器分辨率（`ax_tool.py` 的 `--shot-scale`，默认 `0.9333 = 1372/1470`，换显示器需重算）
- 进程级键盘事件（`CGEventPostToPid`）并非所有 app 都接受：浏览器类通常可以，微信需要前台

## License

MIT
