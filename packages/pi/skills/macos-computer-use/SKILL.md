---
name: macos-computer-use
description: Fast, AX-first computer use on macOS for any agent that can run a shell command. Use when you need to operate a macOS app (Finder, Chrome, Settings, chat apps, ...) — semantic targeting via the accessibility tree, window-scoped input that does not move the user's cursor, clipboard-safe pasting, action read-back verification, blank-frame detection, and optional Jev semantic guards. Replaces "screenshot -> eyeball coordinates -> click and hope".
license: MIT
---

# Fast computer use on macOS (AX-first)

The speed of a good computer-use loop does not come from the model. It comes from
**not** hunting for coordinates in screenshots: read the macOS accessibility (AX)
tree, get each element's semantics (role/title/value) plus exact geometry, then
act on the element.

This skill assumes the `macos-cu` CLI is available. It is not installed with
this package — install it once:

```bash
pip install macos-computer-use-kit
```

This pi package also ships an extension that exposes the CLI as native tools
(`macos_cu_doctor`, `macos_ax_find`, `macos_ax_press`, `macos_input_windows`,
`macos_input_click`, `macos_input_key`, `macos_paste`, `macos_shot`,
`macos_jev_guard`), so inside pi you can call those directly instead of
shelling out. The `macos-cu ...` commands below remain the reference for the
exact arguments each tool forwards.

## Core principles

1. **Locate by AX, execute by coordinates.** `macos-cu ax find` gives exact
   geometry. Never guess from a screenshot.
2. **One shell call does a whole sequence.** Chain `windows -> find -> click ->
   verify` in a single command instead of one round trip per step.
3. **CJK/non-ASCII text goes through the clipboard or AX `setvalue`.** Typing
   character-by-character gets eaten by input methods (ASCII survives, the rest
   does not).
4. **Screenshots are for verification only** — and always run them through
   blank-frame detection first.
5. **Prefer keyboard shortcuts and semantic actions.** Use ⌘F to search, ⌘L to
   focus a URL bar; if `setvalue` works, do not type.

## Coordinate spaces (the #1 source of misclicks)

| Space | Source | Used by |
| --- | --- | --- |
| `screen[x, y]` | AX/CoreGraphics points, origin at the primary display's top-left | `macos-cu input --x --y`, `macos-cu overlay` |
| Window-relative | element point − window origin | `macos-cu input click --window-id N --x --y` |
| `shot[x, y]` | `center_screen * --shot-scale` | only for harnesses whose screenshots are scaled differently from screen points; **there is no safe default, pass it explicitly** |

Secondary displays placed left of or above the primary produce **negative**
coordinates. That is normal, not a bug. Check `macos-cu doctor` for the layout.

## Standard flow

```bash
# 0) one-time environment check (permissions, displays, deps, Jev)
macos-cu doctor

# 1) list windows (main windows first, with a stable target signature)
macos-cu input windows --app "Google Chrome"

# 2) semantic targeting — exact geometry, zero visual reasoning
macos-cu ax find --app com.apple.finder --role AXButton --title Size
macos-cu ax tree --app com.apple.finder --depth 16 --max 200
#    token-efficient: a snapshot with stable ids, trimmed to a character budget
macos-cu ax snapshot --app com.apple.finder --budget 1200 --file /tmp/ax.json
macos-cu ax resolve  --file /tmp/ax.json --id 0.1.0.6.0.0.0.0.5.8

# 3) act — window-scoped input, target validated, visually confirmed
macos-cu input click --window-id 12770 --x 171 --y 28 --show
macos-cu input click --window-id 12770 --x 171 --y 28 --expect "37040:12770:642:244:824:640"
#   mismatch => {"ok":false,"reason":"target_changed",...} and exit code 5
macos-cu input key --app com.google.Chrome --key t --flags cmd

# 4) verify — screenshot with blank-frame detection
macos-cu shot capture --app "Google Chrome" --out /tmp/shot.png
macos-cu shot check --file /tmp/shot.png
```

## The four capabilities that matter

**1. Window-scoped input with target validation.** `macos-cu input` posts events
straight to the target process (`CGEventPostToPid`), so the physical cursor never
moves and the user can keep using their mouse. `--expect pid:wid:x:y:w:h` refuses
to act when the window moved or lost focus since you looked at it.

**2. Native AX actions with read-back verification.**

```bash
macos-cu ax press   --app com.apple.finder --role AXButton --title Size
# {"verified":true,"state_changed":true,"before":{"text_sig":"..."},"after":{...}}
macos-cu ax setvalue --app com.apple.finder --role AXTextField --text "hello"
# {"verified":true,"readback":"hello"}
```

Verification compares the window's visible-text fingerprint and focused element
before/after. When `verified` is false the result carries a `hint` telling you to
fall back to a coordinate click or a clipboard paste. **Custom-drawn UIs do not
support AXPress** — that is expected, and the read-back is how you find out
without guessing.

**3. Clipboard-safe paste.** The user's clipboard is saved before and restored
after, so pasting CJK text never destroys what they had copied. Takeover
(exit 2) and non-consumption (exit 3) are reported explicitly.

```bash
macos-cu paste --app com.google.Chrome --text "你好" --mode pid
```

**4. Blank-frame detection + visual feedback.** Never reason about a black frame:

```bash
macos-cu shot capture --app "Google Chrome" --out /tmp/s.png   # {"verdict":"ok",...}
macos-cu shot check --file /tmp/s.png                          # all_black / all_white / uniform / ok
macos-cu overlay show --x 1417 --y 850 --label "Send" --duration 1.5
```

`input ... --show` calls the overlay for you, so the user can see where the agent
acted.

## Permissions (one-time)

Grant to the process that runs these commands (your terminal, or the agent app):

- **Accessibility** — AX reads, `AXPress`, `setValue`, posted events
- **Screen Recording** — `shot` (otherwise every frame is black)

`macos-cu doctor` reports both and prints exactly what to enable.

## Jev semantic guards (optional)

Jev is a small model that returns typed judgments and calibrated probabilities
rather than text. Use it for **semantic identity, state, and effect** questions
right before irreversible actions; never for things ordinary code already
decides (blank detection, signature comparison, overlay).

```bash
# Pre-action guard: one request fans out four independent judgments.
echo '{"task":"send the report to Alice",
       "expected":{"recipient":"Alice","message":"Q3 numbers"},
       "observed":{"chat_title":"Bob","input_text":"Q3 numbers"}}' | macos-cu jev guard
# => {"answers":{"right_target":0.02,"input_ok":0.98,"blocker":"wrong_target"},
#     "decision":"switch_target"}
# Policy: proceed only when blocker=none and both probabilities clear 0.85.
# The model may only suggest the two safe recoveries (switch_target /
# retype_input); everything else asks the user.

# Element selection with a `none` escape hatch and a confidence gate.
echo '{"goal":"the message input box of the Bob chat",
       "candidates":[{"id":33,"text":"AXTextArea 484x62 Bob"},{"id":49,"text":"AXButton Send"}]}' \
  | macos-cu jev select
# => {"id":"33","confidence":0.94,"gate":"auto"}   (or {"id":"none","gate":"no_match"})
```

Requires `TYPESAFE_API_KEY` or `~/.config/typesafe/api_key`
(keys: <https://console.typesafe.ai/keys>). Everything else in this toolkit works
without it.

Cost ladder: deterministic code (µs) < Jev (~1 s) < visual reasoning (seconds to
tens of seconds). Insert Jev only before irreversible actions and where the rules
are unknown. See `reference/jev-best-practices.md`.

## Known limitations

- macOS only (AX, CGEvent, and ScreenCaptureKit are macOS APIs).
- Custom-drawn UIs (some Electron apps, games, chat apps) expose a shallow or
  uncooperative AX tree. Fall back to screenshots + coordinates when read-back
  fails, not before.
- Process-targeted key events (`CGEventPostToPid`) are accepted by most apps but
  not all: browsers usually accept them in the background; some chat apps require
  the app to be frontmost for typing/pasting.
- The user may be using the machine at the same time. One extra verification
  before a critical action is cheap; a wrong message sent is not.

## Pitfalls worth remembering

1. **Background keystrokes are app-dependent.** A background ⌘V may be ignored
   even though a background ⌘T in a browser works. For text entry and sending,
   bring the app to the front first, then verify.
2. **The clipboard is shared.** Between your copy and the paste, the user can
   overwrite it. Re-read the target's input before sending anything irreversible.
3. **Apps switch context on their own.** Clicking or searching in a chat app can
   silently change the active conversation. Read the conversation title back
   before pasting.
4. **`action_sent` is not `verified`.** Keep "did we emit the event" and "did the
   UI actually change" as separate facts.
