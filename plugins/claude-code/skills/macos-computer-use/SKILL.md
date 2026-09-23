---
name: macos-computer-use
description: AX-first computer use on macOS. Use when you need to operate a Mac app (Finder, Safari/Chrome, System Settings, Notes, Slack, WeChat, any GUI) — read the accessibility tree for exact element geometry and stable refs, act semantically (press, set value, menus, windows, apps) or with background input that never moves the user's cursor, type CJK/emoji safely, verify every action, and fall back to set-of-mark screenshots or on-device OCR only when accessibility is empty. Works through the macos-computer-use MCP tools (macos_*) or the `macos-cu` CLI.
license: MIT
---

# macOS computer use (AX-first)

A good computer-use loop is fast because it does **not** hunt for coordinates
in screenshots. Read the accessibility (AX) tree, get each element's role,
label and exact geometry, act on the element, then verify that the UI changed.

Two equivalent interfaces — use whichever your harness has:

| MCP tool (Claude Code, Codex, Cursor, …) | CLI (`macos-cu …`, any shell) |
| --- | --- |
| `macos_doctor` | `macos-cu doctor` |
| `macos_snapshot` | `macos-cu ax snapshot --app X --interactive` |
| `macos_find` / `macos_element_at` | `macos-cu ax find …` / `macos-cu ax at --x --y` |
| `macos_act` | `macos-cu ax press\|setvalue\|action\|focus --ref R` |
| `macos_click` / `macos_scroll` / `macos_drag` / `macos_hover` | `macos-cu input click\|scroll\|drag\|hover` |
| `macos_type` / `macos_key` | `macos-cu input type --text` / `macos-cu input key --key cmd+l` |
| `macos_app` / `macos_window` / `macos_menu` | `macos-cu app …` / `macos-cu window …` / `macos-cu menu …` |
| `macos_screenshot` / `macos_ocr` | `macos-cu shot capture\|annotate` / `macos-cu ocr` |
| `macos_wait` | `macos-cu ax wait` |

The pi and dsh packages name their tools after the CLI group instead
(`macos_ax_find`, `macos_ax_press`, `macos_input_click`, `macos_shot`, …);
their arguments mirror the CLI flags above.

If neither is available: `pipx install macos-computer-use-kit` (or
`uvx macos-computer-use-kit doctor`).

## The loop

1. **Check once.** `macos_doctor`. Missing Accessibility or Screen Recording →
   tell the user exactly which app to enable (the hint names it) and stop.
2. **Observe semantically.** `macos_snapshot app=<App>` returns one line per
   actionable element: `#ref role size @screen[x,y] label`. Refs are
   content-derived and survive layout changes; path ids do not.
3. **Act on the element, not the pixel.** In order of preference:
   - `macos_menu path="File > Export…"` for anything in the menu bar;
   - `macos_act ref=<ref>` (AXPress) for buttons, links, checkboxes, menu items;
   - `macos_act action=set_value ref=<field> text=…` for text fields;
   - `macos_click x y` at the element's `center_screen` when AX actions do
     nothing (custom-drawn UI);
   - `macos_key key="cmd+l"` for well-known shortcuts.
4. **Verify.** Results separate `action_sent` from `verified`. Re-observe with
   `macos_snapshot diff_against=<previous snapshot path>` (only the changes
   come back), or `macos_wait` for the element you expect, instead of sleeping.
5. **Screenshots last.** `macos_screenshot annotate=true` draws numbered marks
   on interactive elements and returns `mark → ref/center_screen`; use it to
   confirm visual state, or when the tree is thin. `macos_ocr text="Send"` finds
   text on canvas/game/custom UIs where AX is empty.

## Rules that prevent the classic failures

- **Never retry blindly.** Every failure carries `action_sent` and `retry`
  (`reobserve` / `retry` / `never`). If `action_sent` is true, re-observe
  before doing anything non-idempotent again — a second "Send" is a second
  message.
- **`stale_ref` means re-observe**, not "guess the nearest element".
- **Text entry:** `macos_type` (Unicode events: CJK, emoji and accents arrive
  intact, clipboard untouched). Use `method=paste` for long text; it restores
  the user's clipboard. Newlines become Return — in chat apps that sends.
- **Coordinates are global screen points**, origin at the primary display's
  top-left; displays left of/above the primary are negative. Screenshots report
  `origin` and `scale`: `screen = origin + pixel / scale`. Never pass image
  pixels as click coordinates.
- **Window-scoped clicks:** `macos_window action=list` gives each window a
  `signature`; pass it as `expect` to `macos_click` so a moved window is
  refused (`target_changed`) instead of mis-clicked.
- **Background input is app-dependent.** Browsers accept background clicks and
  keys; some chat apps only accept typing when frontmost. If a background
  action does not verify, `macos_app action=activate` then retry once.
- **Electron apps** (Slack, VS Code, Discord…) expose their full tree only
  after the kit enables it on first read — it does so automatically; take a
  second snapshot if the first is nearly empty.
- **The user may be working.** Before an irreversible action, re-read the
  target (window title, recipient, field value) — one extra read is cheap.

## Safety policy (enforced in code, not in the prompt)

- Password managers, auth prompts, Keychain and the login window are refused
  (`sensitive_app`); focused password fields refuse typing
  (`secure_input_active`, `secure_field`). **Ask the user to do those steps.**
- Lock / log-out / force-quit shortcuts are refused (`system_chord_refused`).
- `MACOS_CU_DRY_RUN=1` resolves targets but sends nothing; `MACOS_CU_AUDIT=1`
  appends every action to an audit log (typed text is logged by length only).
- `MACOS_CU_ALLOW_APPS` / `MACOS_CU_DENY_APPS` restrict which apps may receive
  input. Do not try to work around a refusal; report it.

## Optional: Jev semantic guard

Right before an irreversible action (send, submit, delete, pay), a small model
can check *is this the intended target / is the input right / what blocks*:

```bash
echo '{"task":"send the report to Alice",
       "expected":{"recipient":"Alice","message":"Q3 numbers"},
       "observed":{"chat_title":"Bob","input_text":"Q3 numbers"}}' | macos-cu jev guard
# {"decision":"switch_target", ...}
```

The code decides: proceed only on `blocker=none` with both probabilities over
threshold; the model may only suggest the two safe recoveries. Needs
`TYPESAFE_API_KEY`; everything else works without it. See
`reference/jev-best-practices.md`.

## CLI quick reference

```bash
macos-cu doctor
macos-cu ax snapshot --app Finder --interactive --budget 3000
macos-cu ax press    --app Finder --ref 3f9a1c2e
macos-cu ax setvalue --app Notes --role AXTextArea --text "你好"
macos-cu ax wait     --app Safari --role AXButton --title Reload --timeout 10
macos-cu menu select --app TextEdit --path "Format > Make Plain Text"
macos-cu input click --app Safari --x 640 --y 88 --show
macos-cu input type  --app Notes --text "多语言 text ✓"
macos-cu input key   --app Safari --key cmd+l
macos-cu input drag  --app Finder --x 200 --y 300 --to-x 600 --to-y 300
macos-cu app launch  --app Calculator     # or: app activate | quit | open --target URL
macos-cu window move --app Safari --x 0 --y 25
macos-cu shot annotate --app Safari --out /tmp/marks.png
macos-cu ocr --app "Some Game" --text "Start"
```

Exit codes: `0` ok · `2` usage/permission · `3` not found / stale ref ·
`4` capture failed · `5` target changed · `6` refused by policy · `7` timeout.
