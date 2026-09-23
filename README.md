<div align="center">

# macos-computer-use-kit

**AX-first macOS computer use for AI agents: an MCP server and a CLI.**
Agents read the accessibility tree instead of guessing coordinates from
screenshots. Input is posted to the target app in the background, so your
cursor never moves, and every action is verified.

**English** · [简体中文](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/README.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/macos-computer-use-kit?label=PyPI)](https://pypi.org/project/macos-computer-use-kit/)
[![Python](https://img.shields.io/pypi/pyversions/macos-computer-use-kit)](https://pypi.org/project/macos-computer-use-kit/)
[![pi package](https://img.shields.io/npm/v/pi-macos-computer-use?label=pi)](https://www.npmjs.com/package/pi-macos-computer-use)
[![dsh plugin](https://img.shields.io/npm/v/dsh-macos-computer-use?label=dsh)](https://www.npmjs.com/package/dsh-macos-computer-use)
[![CI](https://github.com/Sur-Cai/macos-computer-use-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/Sur-Cai/macos-computer-use-kit/actions/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-stdio-6f42c1)](https://modelcontextprotocol.io)
[![macOS 12+](https://img.shields.io/badge/macOS-12%2B-black?logo=apple)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/LICENSE)

</div>

```text
screenshot → guess coordinates → click → hope      ✗  slow, fragile, moves your mouse
snapshot   → act on #ref       → verify the diff   ✓  what this kit does
```

- **One command per client.** Works with Claude Code, Claude Desktop, Codex,
  Cursor, Gemini CLI, opencode, pi and DeepSeek Harness. It is a stdio MCP
  server with no runtime dependencies beyond pyobjc and Pillow.
- **Accessibility first.** Each element comes back with a stable `#ref`, its
  role, its label and exact screen geometry. Re-observing returns only the
  diff. Electron and Chromium apps get their full tree turned on
  automatically.
- **Background input.** Clicks, keys, scrolls, drags and Unicode typing are
  posted to the target process, so the user can keep working. CJK, emoji and
  accents arrive intact, and the clipboard is left alone.
- **Verified, never optimistic.** Every result separates `action_sent` from
  `verified`. Failures say whether it is safe to `retry`, whether to
  `reobserve`, or whether to `never` retry.
- **Safe by default.** There is a built-in deny list for password managers
  and system auth. The kit refuses to type into a password field that holds
  Secure Event Input, redacts secure fields, and blocks lock, log-out and
  force-quit chords. It also offers a dry-run mode, a size-only audit log and app
  allow/deny lists.
- **Vision only when needed.** Set-of-mark screenshots draw numbered marks
  linked to refs, and on-device Apple Vision OCR returns screen coordinates.
  Both are fallbacks for canvas, game and custom-drawn UI.

## Contents

- [Quick start](#quick-start)
- [Tools](#tools)
- [How an agent should use it](#how-an-agent-should-use-it)
- [Safety and privacy](#safety-and-privacy)
- [CLI reference](#cli-reference)
- [Other agent integrations](#other-agent-integrations)
- [Jev semantic guards (optional)](#jev-semantic-guards-optional)
- [Related projects](#related-projects)
- [Known limitations](#known-limitations)
- [Repository layout](#repository-layout)

## Quick start

### Requirements

- macOS 12 or later, Python 3.10 or later.
- Grant two permissions to the app that runs your agent (your terminal, Claude
  Desktop, Cursor, and so on). `macos-cu doctor` tells you exactly which app
  is missing which permission.
  - **Accessibility**: needed for reading the tree, AX actions and posted input.
  - **Screen Recording**: needed for screenshots and OCR (without it every
    frame is black).

### Claude Code

Pick one of these:

```bash
# A. As a plugin: MCP server, skill and /macos-doctor command
/plugin marketplace add Sur-Cai/macos-computer-use-kit
/plugin install macos-computer-use@macos-computer-use-kit

# B. As a plain MCP server
claude mcp add --scope user macos-computer-use -- uvx macos-computer-use-kit mcp
```

The plugin finds `macos-cu` on your `PATH` and otherwise falls back to `uvx`
or `pipx run`. Nothing has to be pre-installed except [uv](https://docs.astral.sh/uv/)
or pipx.

### Every other client, with one command

```bash
pipx install macos-computer-use-kit          # or: pip install / uv tool install
macos-cu setup claude-code                   # also: claude-desktop, codex, cursor, gemini, opencode
macos-cu setup skill                         # copy the agent skill to Claude, Codex and opencode
macos-cu doctor                              # permissions, displays, OCR, policy
```

`setup` is idempotent and supports `--dry-run`. JSON configs are merged, so
your other servers are preserved, and a `.bak` copy is written before the
first change. `--read-only` registers only the observation tools.

<details>
<summary>Manual MCP config (any client)</summary>

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

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.macos-computer-use]
command = "uvx"
args = ["macos-computer-use-kit", "mcp"]
```

GUI apps do not inherit your shell's `PATH`. Use absolute paths
(`which uvx`) if the client cannot find the command. `macos-cu setup print`
prints the exact argv for your machine.

</details>

## Tools

The MCP server exposes 18 tools. Observation tools carry `readOnlyHint`, so
clients can auto-approve them. To trim the list, use `mcp --read-only`,
`--tools a,b` or `--exclude-tools c`.

| Tool | What it does |
| --- | --- |
| `macos_doctor` | Permissions, display layout (points, Retina scale, negative origins), OCR, policy |
| `macos_snapshot` | Interactive elements as `#ref role size @screen[x,y] label`, trimmed to a character budget; `diff_against` returns only the changes |
| `macos_find` / `macos_element_at` | Find by role or title with exact geometry / hit-test a screen point |
| `macos_act` | Act on an element by ref: `press`, `set_value`, `focus`, or any action it advertises (`AXShowMenu`, `AXIncrement`, …), with read-back verification |
| `macos_click` | Background click: left, right or middle, double or triple, with modifiers; `expect` refuses if the window moved |
| `macos_type` / `macos_key` | Unicode typing (CJK- and emoji-safe) or clipboard-safe paste / keys and chords (`cmd+shift+t`, `mod+s`) |
| `macos_scroll` / `macos_drag` / `macos_hover` | Pointer gestures posted to the target process |
| `macos_app` / `macos_window` / `macos_menu` | Launch, activate, quit or open a URL or file / move, resize, minimize, raise or close windows / menu bar by path (`File > Export…`) |
| `macos_screenshot` | App, window, region or display capture with blank-frame detection; `annotate=true` adds set-of-mark labels |
| `macos_ocr` | Apple Vision OCR with screen rects; `text=` returns only the matches, ready to click |
| `macos_wait` | Wait for an element to appear, disappear or hold a value, instead of sleeping |
| `macos_jev_guard` | Optional semantic check before an irreversible step (see [Jev](#jev-semantic-guards-optional)) |

## How an agent should use it

```text
macos_doctor                                   once: permissions + display layout
macos_snapshot app="Notes"                     → #a1b2c3d4 AXButton 28x28 @screen[812,64] New Note …
macos_act ref="a1b2c3d4"                       → {"ok":true,"action_sent":true,"verified":true}
macos_type app="Notes" text="周会纪要 ✅"        → Unicode events, clipboard untouched
macos_snapshot app="Notes" diff_against=<path> → only what changed
```

The rules behind the loop, which the bundled [skill](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/skill/SKILL.md) teaches:

1. **Observe semantically.** Snapshot before you screenshot.
2. **Act on the element, not the pixel.** Prefer menu paths and AX actions,
   then a click at `center_screen`, then keyboard shortcuts.
3. **Verify, don't sleep.** Use a snapshot diff or `macos_wait`.
4. **Never retry blindly.** If `action_sent` is true, re-observe before
   repeating anything that can't safely run twice. A second "Send" is a
   second message.
5. **`stale_ref` means re-observe.** It never means "pick the nearest element".

### Coordinate spaces

| Space | Meaning | Used by |
| --- | --- | --- |
| `screen[x, y]` | Global points, origin at the primary display's top-left (same as AX and CGEvent) | `macos_click`, `input --x --y`, `overlay` |
| window-relative | element point minus window origin | `macos_click window_id=…` |
| image pixels | screenshot pixels = points × `backing_scale` (Retina: 2) | only when reading a PNG yourself |

Displays placed left of or above the primary have **negative** coordinates.
That is normal, and `macos_doctor` prints the layout.

## Safety and privacy

Everything runs locally. The kit makes no network calls, except the optional
Jev guard, which only runs when you configure a key and call it.

| Guard | Behaviour | Override |
| --- | --- | --- |
| Sensitive apps | Password managers, Keychain Access, Passwords, SecurityAgent, the login window and system auth prompts refuse input | `MACOS_CU_ALLOW_SENSITIVE=1` |
| Secure input | Refuses to type into an app whose password field holds Secure Event Input; secure field values are redacted in every tree and result | — |
| Locked screen | Refuses all input while the screen is locked | — |
| System chords | Lock screen, log out and force quit are refused | `MACOS_CU_ALLOW_SYSTEM_CHORDS=1` |
| App allow/deny | Only / never these bundle ids or names | `MACOS_CU_ALLOW_APPS`, `MACOS_CU_DENY_APPS` |
| Dry run | Resolve targets and report, but post no events | `MACOS_CU_DRY_RUN=1` |
| Audit log | One JSON line per mutating action; typed text is logged as its **length only** | `MACOS_CU_AUDIT=1` |

Local files stay private to your account:

- Snapshot caches and the audit log live in `~/.cache/macos-computer-use/`,
  or wherever `MACOS_CU_CACHE_DIR` points.
- They are created with `0700`/`0600` permissions.
- Snapshots are pruned to the newest 20 (`MACOS_CU_SNAPSHOT_KEEP`).
- Screenshots and OCR captures are written only where you ask (`out=`).
  Temporary OCR captures are deleted.

## CLI reference

Every command prints JSON (or compact text for `ax tree/find/snapshot`), so an
agent can drive the kit from any shell. Exit codes are stable: `0` ok,
`2` usage or permission, `3` not found / stale ref, `4` capture failed,
`5` target changed, `6` refused by policy, `7` timeout.

| Group | Commands |
| --- | --- |
| `macos-cu ax` | `snapshot` (`--interactive`, `--budget`, `--diff`), `find`, `tree`, `at`, `actions`, `press`, `setvalue`, `focus`, `action --name`, `wait`, `resolve` |
| `macos-cu input` | `click` (`--button`, `--count`, `--flags`), `type`, `key` (chords), `scroll`, `drag`, `hover`, `move`, `windows`, `cursor`, `pid` |
| `macos-cu paste` | Clipboard-safe paste that proves the app consumed it and restores the clipboard |
| `macos-cu app` | `list`, `launch`, `activate`, `hide`, `quit`, `open --target URL/file` |
| `macos-cu window` | `list`, `move`, `resize`, `minimize`, `restore`, `raise`, `focus`, `close`, `fullscreen` |
| `macos-cu menu` | `list`, `select --path "File > Export…"` |
| `macos-cu shot` | `capture`, `annotate`, `check`, `windows`, `displays` |
| `macos-cu ocr` | Vision OCR of an app, window, region or file (`--text`, `--lang zh-Hans,en-US`) |
| `macos-cu mcp` / `setup` / `doctor` | Serve MCP / register with a client / diagnose |
| `macos-cu overlay` / `jev` | Visual feedback ring / optional semantic guards |

```bash
macos-cu ax snapshot --app Finder --interactive
macos-cu ax press --app Finder --ref 9d2261d7
macos-cu menu select --app Safari --path "File > New Private Window"
macos-cu input type --app Notes --text "你好, world 👋"
macos-cu input click --window-id 12345 --x 171 --y 28 --expect "<pid:wid:x:y:w:h>"
macos-cu shot annotate --app "System Settings" --out /tmp/marks.png
macos-cu ocr --app Preview --text "Total"
```

## Other agent integrations

The MCP server covers most clients. There are native bridges for two
harnesses that prefer their own tool format. Both are thin wrappers over the
same CLI and call it with argv arrays (`shell: false`).

| Harness | Package | Install |
| --- | --- | --- |
| [pi](https://pi.dev) | [`pi-macos-computer-use`](https://www.npmjs.com/package/pi-macos-computer-use): skill + 16 tools | `pi install npm:pi-macos-computer-use` |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | [`dsh-macos-computer-use`](https://www.npmjs.com/package/dsh-macos-computer-use): Cordis bundle, 11 tools | `dsh plugin --profile <name> add dsh-macos-computer-use` |
| opencode | skill + MCP entry | `macos-cu setup opencode` (or `./install.sh` from a checkout) |

Install the CLI first (`pipx install macos-computer-use-kit`). If an app
launched from the Dock can't find it, set `MACOS_CU_BIN=/abs/path/to/macos-cu`.
All artifacts share one version number and are released together. See
[`packages/pi`](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/packages/pi/README.md) and [`packages/dsh`](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/packages/dsh/README.md)
for details.

## Jev semantic guards (optional)

This is the only feature that needs a key. Right before an irreversible step,
a small model gives calibrated judgments: *is this still the intended
recipient? does the field hold the intended text? what blocks the action?*
**Code** decides whether to proceed, and the model may only suggest the two
recoveries that cannot send anything.

```bash
echo '{"task":"send the report to Alice",
       "expected":{"recipient":"Alice","message":"Q3 numbers"},
       "observed":{"chat_title":"Bob","input_text":"Q3 numbers"}}' | macos-cu jev guard
# {"answers":{"right_target":0.02,"input_ok":0.98,"blocker":"wrong_target"},"decision":"switch_target"}
```

The key is read from `TYPESAFE_API_KEY` or `~/.config/typesafe/api_key`
(<https://console.typesafe.ai/keys>). Question design is covered in
[`skill/reference/jev-best-practices.md`](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/skill/reference/jev-best-practices.md).

## Related projects

Computer use is a busy space. These are the projects worth knowing, with star
counts as of September 2026. Pick the one that fits.

| Project | Platform · language | Pick it when you want… |
| --- | --- | --- |
| [trycua/cua](https://github.com/trycua/cua) ★26k | macOS/Linux/Windows · Swift/Rust/Py | VM sandboxes (Lume), a driver + benchmarks, cross-platform agents |
| [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) ★39k | cross-platform · TS | a vision-model-driven desktop agent app |
| [microsoft/OmniParser](https://github.com/microsoft/OmniParser) ★25k | any · Py | screenshot → UI elements, for pure-vision agents |
| [microsoft/UFO](https://github.com/microsoft/UFO) ★10k | Windows · Py | a Windows UI Automation agent OS |
| [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP) ★7k | Windows · Py | the Windows counterpart of this kit |
| [openclaw/Peekaboo](https://github.com/openclaw/Peekaboo) ★5k | macOS · Swift | a native Swift CLI and menu-bar app with annotated screenshots |
| [iFurySt/open-codex-computer-use](https://github.com/iFurySt/open-codex-computer-use) ★2k | macOS/Linux/Windows · Swift | an open clone of Codex's computer-use tool surface |
| [ghostwright/ghost-os](https://github.com/ghostwright/ghost-os) ★2k | macOS · Swift | AX-first MCP with a learn-by-demonstration recorder |
| [lahfir/agent-desktop](https://github.com/lahfir/agent-desktop) ★2k | macOS · Rust | an AX CLI with skeleton-then-drill traversal |

**Where this kit fits.** It is pure Python on pyobjc, so there's no binary to
notarize: `uvx` runs it anywhere. Its focus is agent-loop reliability. That
means verified results with retry semantics, stale-ref detection, snapshot
diffs, and a deterministic safety policy. The optional Jev guard adds a
calibrated check before irreversible steps. The design follows the patterns
mature computer-use agents converged on, reimplemented from scratch.

## Known limitations

- macOS only. AX, CGEvent, ScreenCaptureKit and Vision are macOS APIs.
- Custom-drawn UIs (games, canvases, some chat apps) expose little or no
  accessibility data. Use `annotate`, `ocr` and coordinate clicks there, and
  verify visually.
- Most apps accept background input, but a few only accept typing or pasting
  while frontmost. Use `macos_app action=activate` first.
- The user may be working at the same time. One extra verification before an
  irreversible step is cheap.

## Repository layout

```text
src/macos_computer_use/   the CLI + MCP server (single source of truth)
skill/                    the agent skill (canonical; synced by scripts/sync-skill.sh)
plugins/claude-code/      Claude Code plugin (MCP launcher, skill, /macos-doctor)
.claude-plugin/           marketplace manifest for `/plugin marketplace add`
packages/pi/              pi package (skill + native tools)
packages/dsh/             DeepSeek Harness bundle
tests/                    unit tests: policy, chords, diffs, OCR geometry, MCP protocol
tools/*.py                legacy script shims over the same modules
```

See [CONTRIBUTING.md](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/CONTRIBUTING.md) for conventions,
[PUBLISHING.md](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/PUBLISHING.md) for release steps and
[CHANGELOG.md](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/CHANGELOG.md) for the changelog.

## License

[MIT](https://github.com/Sur-Cai/macos-computer-use-kit/blob/main/LICENSE)
