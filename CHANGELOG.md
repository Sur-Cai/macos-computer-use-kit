# Changelog

All notable changes to this project. The CLI, the pi package, and the dsh bundle
share a version number.

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
