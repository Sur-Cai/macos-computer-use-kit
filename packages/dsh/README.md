# dsh-macos-computer-use

DeepSeek Harness (dsh) bundle bridging dsh agents to the
[macos-computer-use-kit](https://github.com/Sur-Cai/macos-computer-use-kit)
`macos-cu` CLI: AX-first computer use on macOS.

The plugin registers five focused tools that shell out to `macos-cu` with an
argument array (never shell-string concatenation) and return the CLI's JSON
output:

| Tool | CLI call | Purpose |
| --- | --- | --- |
| `macos_cu_doctor` | `macos-cu doctor` | Permissions/displays/deps/Jev diagnostics — run first |
| `macos_ax_find` | `macos-cu ax find\|tree` | Semantic element lookup with exact geometry |
| `macos_ax_press` | `macos-cu ax press\|setvalue` | Native AX action with read-back verification |
| `macos_input_click` | `macos-cu input click` | Window-scoped click that never moves the user's cursor |
| `macos_shot` | `macos-cu shot capture\|check\|windows` | Blank-frame-checked screenshots for verification only |

The AX-first intent is baked into every tool description: locate elements via
`macos_ax_find` and use the returned geometry — use instead of guessing
coordinates from a screenshot.

## Install

From a profile (npm registry):

```sh
dsh plugin --profile <name> add dsh-macos-computer-use
```

From git sources (builds `lib/` via the `prepare` script — allowlist the build
when pnpm asks, then re-run the `add`):

```sh
dsh plugin --profile <name> add github:Sur-Cai/macos-computer-use-kit#packages/dsh
```

From a tarball (prebuilt, no build permission needed):

```sh
npm pack ./packages/dsh
dsh plugin --profile <name> add ./dsh-macos-computer-use-0.2.0.tgz
```

Verify the layer without booting, then boot:

```sh
dsh --profile <name> --dump-config   # shows a "# == dsh-macos-computer-use" layer
dsh --profile <name>
```

## Prerequisites

- macOS (AX, CGEvent, and ScreenCaptureKit are macOS APIs).
- The `macos-cu` binary on PATH: `pip install macos-computer-use-kit`
  (or run from a checkout; override with `MACOS_CU_BIN=/path/to/macos-cu`).
  Every tool detects a missing binary and returns this instruction instead of
  failing obscurely.
- One-time macOS grants for the process hosting dsh: **Accessibility** (AX
  reads, `AXPress`, `setValue`, posted events) and **Screen Recording**
  (`shot`, otherwise every frame is black). `macos_cu_doctor` reports both.
- Optional: `TYPESAFE_API_KEY` for the CLI's Jev semantic guards
  (`macos-cu jev guard|select`, invoked via shell — no dedicated tool here).

## Computer-use slot decision

This bundle **only adds tools; it deliberately does NOT call
`ctx.computerUse.register()`** and therefore does not claim the single
provider slot (`@deepseek-ai/dsh-computer-use` rejects any second provider):

- The bridge shells out to an external macOS-only CLI rather than
  implementing a provider-owned tool catalog and desktop-operation lifecycle,
  so it cannot honor the provider contract (stop tools and await owned work
  before releasing the registration).
- Claiming the exclusive slot would block Cua Driver (or any other) provider
  in the same composition on machines where this bundle is installed but
  unusable (non-macOS hosts, missing permissions).
- Users who want exclusivity can coordinate at the composition level; nothing
  here prevents a future native provider from registering the slot.

## Development

```sh
cd packages/dsh
npm install
npm run build      # tsc -> lib/ (also runs automatically as `prepare` on git installs)
npm run typecheck
```

`lib/` is built output and is not committed; npm installs from the registry
ship it prebuilt, while git installs rebuild it via `prepare` (self-contained
`tsc`, no monorepo project references).

License: MIT (see `LICENSE`).
