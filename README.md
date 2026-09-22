# macos-computer-use-kit

**AX-first computer use for AI agents on macOS.** Instead of screenshot → eyeball
coordinates → click and hope, read the accessibility tree, get each element's
semantics and exact geometry, act on it, then verify the action actually changed
the UI.

A small, composable toolkit: accessibility-tree targeting, process- and
window-scoped input, clipboard-safe pasting, action read-back verification,
blank-frame detection, visual feedback, and optional Jev (TypeSafe System One)
semantic guards.

Works with any agent that can run a shell command, and ships first-class
packages for [pi](#pi) and [DeepSeek Harness](#deepseek-harness-dsh).

## Why

These mechanisms were distilled from three mature implementations rather than
invented from scratch:

| Source | Mechanism absorbed |
| --- | --- |
| Codex CUA (`@oai/cua` / Sky service) | AX state + element index, `setValue`, batch actions, event delivery via `CGEventPostToPid` |
| ZCode Computer Use | `*_to_window` window-scoped input, `target_changed` validation, clipboard-safe paste pipeline, `screenshot_blank` |
| Grok Bot (`CUGrokBotService`) | snapshots with stable element ids + text budget + drill-down, action read-back, coordinate fallback on failure |

## Install

macOS 12+, Python 3.10+.

```bash
pip install macos-computer-use-kit        # or: pipx install macos-computer-use-kit
macos-cu doctor                           # check permissions, displays, dependencies

# from a checkout (editable install + agent skill)
git clone https://github.com/Sur-Cai/macos-computer-use-kit && cd macos-computer-use-kit
./install.sh
```

Grant both permissions to the process that runs the agent (your terminal, or the
agent app). `macos-cu doctor` reports what is missing and where to enable it:

- **Accessibility** — AX reads, `AXPress`, `setValue`, posted events
- **Screen Recording** — `shot` (without it every capture is black)

## Quickstart

```bash
# semantic targeting: exact geometry, zero visual reasoning
macos-cu ax find --app com.apple.finder --role AXButton --title Size
macos-cu ax tree --app com.apple.finder --depth 16 --max 200

# token-efficient snapshot with stable ids, trimmed to a budget
macos-cu ax snapshot --app com.apple.finder --budget 1200 --file /tmp/ax.json
macos-cu ax resolve  --file /tmp/ax.json --id 0.1.0.6.0.0.0.0.5.8

# native AX action + read-back verification
macos-cu ax press --app com.apple.finder --role AXButton --title Size
# {"verified":true,"state_changed":true,...}

# window-scoped input: the user's cursor never moves, target is validated
macos-cu input windows --app "Google Chrome"
macos-cu input click --window-id 12345 --x 171 --y 28 --show
macos-cu input click --window-id 12345 --x 171 --y 28 --expect "37040:12345:642:244:824:640"
# mismatch -> {"ok":false,"reason":"target_changed"} and exit code 5

# clipboard-safe paste (saves and restores the user's clipboard)
macos-cu paste --app com.google.Chrome --text "你好" --mode pid

# screenshot with blank-frame detection
macos-cu shot capture --app "Google Chrome" --out /tmp/shot.png
macos-cu shot check --file /tmp/shot.png
```

## CLI

One binary, JSON output, stable exit codes (`0` ok, `2` usage/permission,
`3` not found, `4` capture failed, `5` target changed).

| Group | Commands |
| --- | --- |
| `macos-cu ax` | `tree`, `find`, `click-info`, `snapshot`, `resolve`, `press`, `setvalue` |
| `macos-cu input` | `windows`, `cursor`, `pid`, `click`, `key`, `scroll`, `move` |
| `macos-cu paste` | clipboard-safe paste (`--mode pid\|hid`, `--keep`) |
| `macos-cu shot` | `capture`, `check`, `windows` |
| `macos-cu overlay` | `show`, `clear` |
| `macos-cu jev` | `guard`, `select` (optional, JSON on stdin) |
| `macos-cu doctor` | permissions, displays, dependencies, Jev setup |

### Coordinate spaces

| Space | Source | Used by |
| --- | --- | --- |
| `screen[x, y]` | AX/CoreGraphics points, origin at the primary display's top-left | `input --x --y`, `overlay` |
| window-relative | element point − window origin | `input click --window-id N --x --y` |
| `shot[x, y]` | `center_screen × --shot-scale` | only for harnesses whose screenshots are scaled differently from screen points; there is deliberately no default |

Secondary displays placed left of or above the primary produce **negative**
coordinates. That is normal. `macos-cu doctor` prints the layout.

## Agent integrations

| Harness | What you get | Install |
| --- | --- | --- |
| any agent with a shell | the full CLI | `pip install macos-computer-use-kit` |
| [opencode](https://opencode.ai) | skill `macos-computer-use` (auto-discovered) | `./install.sh` |
| [pi](https://pi.dev) | skill + 9 native tools | `pi install npm:pi-macos-computer-use` |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | plugin bundle, 5 tools | `dsh plugin --profile <name> add dsh-macos-computer-use` |

<a name="pi"></a>
### pi package

`packages/pi` — `pi-macos-computer-use` (npm, `pi-package` keyword). Registers
`macos_cu_doctor`, `macos_ax_find`, `macos_ax_press`, `macos_input_windows`,
`macos_input_click`, `macos_input_key`, `macos_paste`, `macos_shot`,
`macos_jev_guard`. Every tool shells out with an argv array (`shell: false`), so
model-supplied text can never reach a shell.

```bash
pi install npm:pi-macos-computer-use
pi -e ./packages/pi        # try it for one run without installing
```

App launchers do not inherit your interactive shell's `PATH`. If the CLI is
installed but pi cannot find it, set `MACOS_CU_BIN=/abs/path/to/macos-cu` and
restart pi (the dsh plugin honours the same variable).

<a name="deepseek-harness-dsh"></a>
### DeepSeek Harness plugin

`packages/dsh` — `dsh-macos-computer-use`, a Cordis bundle
(`dsh.bundle.patch` → `cordis.patch.yml`). Registers `macos_cu_doctor`,
`macos_ax_find`, `macos_ax_press`, `macos_input_click`, `macos_shot`.

```bash
dsh plugin --profile demo add dsh-macos-computer-use
dsh --profile demo --dump-config    # verify the layer before booting
```

It deliberately does **not** claim the exclusive `ctx.computerUse` provider slot:
it adds tools rather than owning desktop operations, so it cannot block the
in-box Cua Driver provider. See `packages/dsh/README.md`.

### opencode skill

`./install.sh` installs `skill/SKILL.md` to
`~/.config/opencode/skills/macos-computer-use/`, where opencode discovers it
automatically.

## The four capabilities that matter

**1. Window-scoped input with target validation.** Events are posted straight to
the target process (`CGEventPostToPid`), so the physical cursor never moves and
the user can keep working. `--expect pid:wid:x:y:w:h` refuses to act when the
window moved or lost focus since you looked at it.

**2. Native AX actions with read-back verification.** `press`/`setvalue` compare
the window's visible-text fingerprint and focused element before and after, and
report `verified` separately from `action_sent`. When AX cannot act (custom-drawn
UI), the result carries a `hint` telling you to fall back to a coordinate click
or a clipboard paste — you find out from evidence, not from guessing.

**3. Clipboard safety.** The user's clipboard is saved before and restored after.
Takeover and non-consumption are reported explicitly, so pasting CJK text never
silently destroys what the user had copied.

**4. Never reason on a blank frame.** `shot` classifies captures as
`ok` / `all_black` / `all_white` / `uniform` with a hint, so a missing permission
or an occluded window is reported instead of hallucinated UI state.

## Design principles

1. **AX-first.** Semantic + exact geometry beats visual inference. Screenshots
   verify; they do not target.
2. **`action_sent` ≠ `verified`.** Keep "we emitted the event" and "the UI
   changed" as separate facts.
3. **The clipboard is a shared resource.** Save, detect interference, restore.
4. **Targets must be explicit and checkable.** Window input carries a signature;
   a mismatch is `target_changed`, not a misclick.
5. **Small models judge, code decides.** Jev returns calibrated probabilities;
   thresholds and side effects stay in code. Cost ladder: deterministic code
   (µs) < Jev (~1 s) < visual reasoning (seconds to tens of seconds).
6. **Make it visible.** Action points draw a ring, so the user is never watching
   a black box.

## Jev semantic guards (optional)

The only part that needs a key. Everything else works without it.

```bash
echo '{"task":"send the report to Alice",
       "expected":{"recipient":"Alice","message":"Q3 numbers"},
       "observed":{"chat_title":"Bob","input_text":"Q3 numbers"}}' | macos-cu jev guard
# {"answers":{"right_target":0.02,"input_ok":0.98,"blocker":"wrong_target"},
#  "decision":"switch_target"}
```

One request fans out independent judgments and **code** applies the policy:
proceed only when `blocker=none` and both probabilities clear the threshold; the
model may only suggest the two safe recoveries (`switch_target`, `retype_input`);
anything else asks the user. `macos-cu jev select` picks one candidate element
with a `none` escape hatch and a confidence gate.

Key: `TYPESAFE_API_KEY` or `~/.config/typesafe/api_key`
(<https://console.typesafe.ai/keys>). Pin `TYPESAFE_MODEL` for automation;
`jev-latest` is the friendly default. Question-design guidance lives in
[`skill/reference/jev-best-practices.md`](skill/reference/jev-best-practices.md).

## Known limitations

- macOS only (AX, CGEvent, ScreenCaptureKit are macOS APIs).
- Custom-drawn UIs (some Electron apps, games, chat apps) expose shallow or
  uncooperative AX trees. Fall back to screenshots **after** read-back fails,
  not before.
- Process-targeted key events are accepted by most apps but not all: browsers
  usually accept background keystrokes; some chat apps require the app to be
  frontmost for typing and pasting.
- AX coordinate scale is display-dependent. `center_shot` is opt-in via
  `--shot-scale` for exactly this reason.
- The user may be using the machine at the same time. Concurrent automation is
  risky; one extra verification before an irreversible action is cheap.

## Repository layout

```
src/macos_computer_use/   the CLI implementation (pip-installable)
tools/*.py                compatibility shims -> the same modules
skill/                    agent skill (SKILL.md + Jev reference)
packages/pi/              pi package (skill + native tools)
packages/dsh/             DeepSeek Harness plugin bundle
install.sh                local installer (venv + CLI + skill + Jev key)
tests/                    unit tests for the safety-relevant logic
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the
conventions (JSON on stdout, stable exit codes, no machine-specific defaults).
Release steps and catalog-listing criteria live in
[PUBLISHING.md](PUBLISHING.md); notable changes are in
[CHANGELOG.md](CHANGELOG.md).

## 中文说明

给 AI agent 用的 macOS 电脑控制工具箱：**AX 语义定位**（不靠截图目测坐标）、
进程/窗口级输入（物理光标不动）、剪贴板安全粘贴、动作回读校验、空白帧检测、
可视反馈，以及可选的 Jev 语义护栏。

```bash
pip install macos-computer-use-kit
macos-cu doctor          # 检查辅助功能 / 屏幕录制权限、显示器、依赖、Jev
```

Agent 集成：`./install.sh`（opencode skill）、`pi install npm:pi-macos-computer-use`（pi）、
`dsh plugin --profile <名> add dsh-macos-computer-use`（DeepSeek Harness）。
完整流程与避坑见 [`skill/SKILL.md`](skill/SKILL.md)。

## License

MIT
