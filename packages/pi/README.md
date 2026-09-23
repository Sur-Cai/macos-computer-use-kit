# pi-macos-computer-use

AX-first computer use on macOS for [pi](https://pi.dev), backed by the
[`macos-cu`](https://github.com/Sur-Cai/macos-computer-use-kit) CLI.

Most computer-use loops are slow because the model hunts for coordinates in
screenshots. This package gives pi tools that read the macOS **accessibility
tree** instead: every element comes back with its role, title, value, and exact
geometry, so the model targets an element rather than eyeballing a picture.

## Install

```bash
pi install npm:pi-macos-computer-use
```

The npm package ships the extension and the skill. The CLI itself is a separate
Python install (it needs macOS system APIs):

```bash
pip install macos-computer-use-kit
# or, if your Python is system-managed:
pipx install macos-computer-use-kit
```

Then check the environment once:

```bash
macos-cu doctor
```

If `macos-cu` is not on `PATH`, every tool in this package returns an install
hint instead of failing silently.

An app launched from the Dock or Finder does **not** inherit an interactive
shell's `PATH`. If the CLI is installed but pi still reports it missing, point
this extension at the binary and restart pi:

```bash
export MACOS_CU_BIN="$HOME/.local/bin/macos-cu"   # or whichever path `which macos-cu` prints in your shell
```

## Prerequisites

- macOS (AX, `CGEventPostToPid`, and ScreenCaptureKit are macOS APIs)
- Python 3.10+ with the `macos-cu` CLI installed
- Two permissions, granted to the process that runs pi (Terminal, iTerm, or the
  pi app) — `macos-cu doctor` prints exactly what to enable:
  - **Accessibility** — AX reads, `AXPress`, `setValue`, posted events
  - **Screen Recording** — `macos_shot` and `macos_ocr` (without it every
    frame is black)
- Optional: `TYPESAFE_API_KEY` (or `~/.config/typesafe/api_key`) for
  `macos_jev_guard`. Everything else works without it.

## Tools

| Tool | What it does |
| --- | --- |
| `macos_cu_doctor` | Permissions, displays, dependencies, OCR, safety policy, Jev setup |
| `macos_ax_find` | Elements by AX role/title with exact screen geometry and stable refs; also `tree`, `snapshot` (budgeted, `--interactive`, diff) and `resolve` modes |
| `macos_ax_press` | Native `AXPress` / `setValue` / focus / named AX actions by ref, with read-back verification (`verified: true/false`) |
| `macos_input_windows` | Window ids, geometry, and the `pid:wid:x:y:w:h` target signature |
| `macos_input_click` | Background click (left/right/middle, double/triple, modifiers) without moving the user's cursor; `expect` refuses a moved window |
| `macos_input_key` | Keys and chords (`cmd+shift+t`, `mod+s`); lock / log-out / force-quit are refused |
| `macos_type` | Unicode typing: CJK, emoji and accents arrive intact, clipboard untouched |
| `macos_paste` | Clipboard-safe paste that proves the app consumed it and restores the user's clipboard |
| `macos_pointer` | Scroll, drag and hover posted to the target process |
| `macos_app` | List, launch, activate, hide, quit apps; open URLs and files |
| `macos_window` | Move, resize, minimize, restore, raise, focus, close, fullscreen windows |
| `macos_menu` | Menu bar by path (`File > Export…`), works with the app in the background |
| `macos_shot` | Capture plus blank-frame detection; `annotate` draws set-of-mark labels |
| `macos_ocr` | On-device Apple Vision OCR with screen coordinates |
| `macos_wait` | Wait for an element to appear, disappear or hold a value |
| `macos_jev_guard` | Optional Jev semantic guards before irreversible actions |

Every tool returns the CLI's JSON output verbatim. Arguments are passed to the
CLI as an argv array (`execFile`, `shell: false`), so model-supplied text can
never be interpreted by a shell. Long output is head-truncated at pi's standard
limits and the full text is written to a temp file.

No tool moves the physical mouse cursor: events are posted straight to the
target process, so the user can keep using their machine while pi works.

## Skill

`skills/macos-computer-use/SKILL.md` documents the full workflow —
coordinate spaces, the standard `windows -> find -> act -> verify` loop,
permissions, the Jev cost ladder, and the pitfalls worth remembering. pi loads
it on demand when a task matches.

## What the CLI guarantees

- `verified` is not `action_sent`: the CLI re-reads the window's visible text
  and focused element after an AX action, and reports both facts separately.
- `input ... --expect` turns a moved window into `{"ok":false,"reason":"target_changed"}`
  (exit code 5) instead of a mis-click.
- Blank-frame detection runs before the model ever sees an image.

See the [repository README](https://github.com/Sur-Cai/macos-computer-use-kit)
for the CLI's full command reference and the reasoning behind it.

## Development

TypeScript extensions are loaded by pi through
[jiti](https://github.com/unjs/jiti), so there is no build step. Type checking:

```bash
npm install
npm run typecheck
```

`extensions/` and `skills/` are declared in the `pi` manifest in
`package.json`; the `pi-package` keyword is what lists the package in the
[pi package gallery](https://pi.dev/packages).

## License

MIT
