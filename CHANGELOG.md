# Changelog

All notable changes to this project. The CLI, the pi package, and the dsh bundle
share a version number.

## 0.3.1

Security fix in the safety policy's app matching.

- **Bundle ids now match at vendor granularity with a dot boundary.** The
  sensitive-app list and the `MACOS_CU_DENY_APPS` / `MACOS_CU_ALLOW_APPS` lists
  compared bundle ids for exact equality, so a password manager's helper or beta
  process (`com.lastpass.helper`, `com.agilebits.onepassword8`,
  `com.bitwarden.desktop.helper`) was treated as an unrelated app and could
  receive input. `com.lastpass` now covers `com.lastpass.helper`; a string
  prefix without a dot boundary (`com.lastpass2`) still does not match.
- **The name-hint substring rule used `len(hint) > 8`**, which silently excluded
  `lastpass`, `dashlane` and `nordpass` — exactly 8 characters — from substring
  matching, so "LastPass Helper" was not recognised by name either. The floor is
  now inclusive.
- Ordinary apps are unaffected, and an app whose *name* merely contains a
  product name is still refused (fail-closed). Both directions are covered by
  five new tests.

## 0.3.0

The toolkit becomes an MCP server with first-class Claude Code support, and
gains the action surface and safety layer that agent loops need.

**MCP and agent clients**
- `macos-cu mcp`: a dependency-free stdio MCP server with 18 tools. Observation
  tools carry `readOnlyHint`. The tool list can be trimmed with `--read-only`,
  `--tools` and `--exclude-tools`, and `--list-tools` prints it.
- Claude Code plugin + marketplace (`/plugin marketplace add
  Sur-Cai/macos-computer-use-kit`): the MCP server, the skill and a
  `/macos-doctor` command. The launcher resolves `macos-cu`, then `uvx`, then
  `pipx run`.
- `macos-cu setup claude-code|claude-desktop|codex|cursor|gemini|opencode|skill|print`:
  idempotent registration with `--dry-run`. JSON configs are merged, with a
  one-time `.bak` backup.
- New `macos-computer-use-kit` console script, so `uvx macos-computer-use-kit mcp`
  works without `--from`. The skill ships inside the wheel.

**Observation**
- Stable, content-derived element refs (`#9d2261d7`) that survive layout churn.
  `--ref` works in `press`/`setvalue`/`focus`/`action`/`actions`/`wait`, and a
  ref that no longer resolves returns `stale_ref` instead of acting on a guess.
- `ax snapshot --interactive --budget N` trims a large tree to the elements
  worth acting on; `--diff <earlier snapshot>` returns only what was added,
  removed or changed.
- `ax at` (hit-test), `ax actions`, `ax action --name AXShowMenu|AXIncrement|…`,
  `ax focus`, `ax wait` (appear / `--gone` / `--value`, exit 7 on timeout).
- Electron/Chromium: the full tree is enabled automatically via
  `AXManualAccessibility` / `AXEnhancedUserInterface` when a walk comes back
  nearly empty.
- AX calls are capped by a messaging timeout (`MACOS_CU_AX_TIMEOUT`, default
  3 s), so a hung app cannot hang the agent.
- `shot annotate` (set-of-mark labels linked to refs), `shot displays`,
  `--region`, `--display`, `--crop`, inline `--base64` with `--max-width`.
- `ocr`: on-device Apple Vision OCR with screen coordinates, `--text` matching and
  `--lang`. No extra dependency; the system framework is loaded directly.

**Action**
- `input type`: Unicode key events, so CJK, emoji and accents arrive intact
  without touching the clipboard.
- `input key` accepts chords (`cmd+shift+t`, `mod+s`, `f5`) and `--repeat`.
- `input click --button right|middle --count 2|3 --flags cmd+shift`; new
  `drag`, `hover`, and pixel/line `scroll` with horizontal `--dx`.
- `app list|launch|activate|hide|quit|open`, `window list|move|resize|minimize|restore|raise|focus|close|fullscreen`,
  `menu list|select --path "File > Export…"`.

**Reliability and safety**
- Uniform result envelope: `ok`, `reason`, `action_sent`, and
  `retry: reobserve|retry|never`, plus stable exit codes `6` (policy) and `7` (timeout).
- Deterministic policy in front of every input:
  - a built-in sensitive-app deny list (password managers, Keychain Access,
    Passwords, SecurityAgent, login window and auth prompts);
  - a Secure Event Input check before typing, and a locked-screen check;
  - lock / log-out / force-quit chords refused;
  - `MACOS_CU_ALLOW_APPS` / `MACOS_CU_DENY_APPS` allow/deny lists and
    `MACOS_CU_DRY_RUN`.
- `MACOS_CU_AUDIT=1` appends one JSON line per mutating action. Typed text is
  recorded by length only.
- Secure text fields are redacted in every tree, snapshot and fingerprint.
- Snapshot caches and the audit log are created `0700`/`0600`, and snapshots
  are pruned to the newest 20 (`MACOS_CU_SNAPSHOT_KEEP`).
- `doctor` reports display `bounds` in the top-left point space that AX and
  CGEvent use (secondary displays may be negative), plus OCR and policy status.

**Integrations**
- pi package: 16 tools (adds `macos_type`, `macos_pointer`, `macos_app`,
  `macos_window`, `macos_menu`, `macos_ocr`, `macos_wait`).
- dsh bundle: 11 tools (adds `macos_type`, `macos_key`, `macos_app`,
  `macos_menu`, `macos_ocr`).
- One canonical skill in `skill/`, copied into every package by
  `scripts/sync-skill.sh` (checked in CI).

**Docs**
- The README was rewritten, and a Chinese translation was added
  (`README.zh-CN.md`, with a language switcher). It adds a tools table, a
  safety and privacy section, and an index of related projects.

## 0.2.2

Discoverability and parity for the optional Jev (TypeSafe System One) guards.

- **The dsh bundle now exposes `macos_jev_guard`** — the same optional semantic
  guard the pi package already had — so both integrations carry the capability
  they advertise (6 tools instead of 5). The bridge gained stdin support, which
  is how `macos-cu jev` receives its JSON request.
- npm keywords gain `jev`, `typesafe-ai`, `system-one-models`; PyPI keywords gain
  `jev`, `typesafe-ai`, `system-one`, `llm-guardrails`. Keywords are immutable
  per version, which is why this needed a release rather than an edit.
- Declare the `Programming Language :: Python :: 3.14` classifier. The wheel has
  installed and run on 3.14 since 0.2.0; only the metadata was behind.

No behaviour changes outside the new tool.

## 0.2.1

- Publish the Python package metadata with an SPDX license expression
  (`license = "MIT"` + `license-files`, PEP 639) instead of embedding the full
  MIT text in the metadata `License` field. No code or behaviour changes.

## 0.2.0

First release meant for use outside the machine it was built on.

**Packaging**
- Ship an installable Python package (`macos-computer-use-kit`) with a `macos-cu`
  console script. Previously the toolkit was a folder of scripts plus a
  hand-made virtualenv at a fixed absolute path.
- `tools/*.py` remain as compatibility shims over the same modules.
- Add `packages/pi` (`pi-package`: skill + 9 tools) and `packages/dsh` (Cordis
  bundle: `cordis.patch.yml` + 5 tools). Both bridge to the CLI with argv arrays
  (`shell: false`) and resolve it from known install locations, so a
  GUI-launched agent works without an interactive shell's `PATH`.
- `install.sh` now provisions a venv, a launcher, the agent skill, and the
  optional Jev key, and picks whichever package index answers faster.

**Portability fixes**
- Remove the hardcoded display scale (`0.9333 = 1372/1470`); `--shot-scale` is
  explicit opt-in and there is no fake default.
- Stop hardcoding the overlay path, the snapshot cache directory, and the
  `/tmp/shot.png` capture path.
- Add `unsupported_platform` / `missing_dependency` JSON errors instead of a
  pyobjc traceback or a shell error.
- Deterministic app resolution: exact bundle id, exact localized name,
  case-insensitive exact, then substring; frontmost apps win ties. The old
  behaviour took the first substring match, which could target the wrong app.
- Prefer `NSPasteboardTypeString`, falling back to the legacy
  `NSStringPboardType`.

**Behaviour fixes**
- `ax find` now honours `--max` (it used to return every match, flooding
  context).
- `input windows --pid` actually filters by pid.
- `doctor` reports platform, permissions, display geometry, dependencies, and
  Jev setup as JSON, with actionable hints.
- The Jev guard policy is a pure `decide()` function; the model version is
  pinnable with `TYPESAFE_MODEL`.

**Documentation**
- English-first README and skill, with a concise Chinese section; machine- and
  app-specific walkthroughs replaced by generic examples.
- `PUBLISHING.md` with the npm/PyPI release steps and catalog-listing criteria.
- Correct the dependency list (`pyobjc-framework-AppKit` does not exist; AppKit
  ships in `pyobjc-framework-Cocoa`).

**Tests and CI**
- Unit tests for the guard policy and the window target signature.
- GitHub Actions: tests and a compile check on macOS, typecheck for both npm
  packages.

## 0.1.0

Initial extraction of the toolkit from three implementations (Codex CUA, ZCode
Computer Use, Grok Bot), with `ax_tool.py`, `assist.py`, `smart_paste.py`,
`shot.py`, `overlay.py`, `guard.py`, `jev_select.py`, and an agent skill.
