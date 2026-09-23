# Contributing

Bug reports, platform findings, and pull requests are welcome. This toolkit
drives real desktops, so evidence beats opinion: paste the JSON a command
returned, the macOS version, and the app you were driving.

## Layout

```
src/macos_computer_use/   the CLI + MCP server (single source of truth)
skill/                    canonical agent skill + Jev reference
plugins/claude-code/      Claude Code plugin (MCP launcher, skill copy, commands)
.claude-plugin/           marketplace manifest
packages/pi/              pi package (skill copy + tools; sources, no build)
packages/dsh/             DeepSeek Harness bundle (TypeScript -> lib/)
scripts/sync-skill.sh     copies skill/ into the plugin and the pi package
tests/                    unit tests for pure logic
tools/*.py                compatibility shims over the same modules
```

## Develop

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
macos-cu doctor
macos-cu mcp --list-tools
scripts/sync-skill.sh --check

(cd packages/pi  && npm ci && npm run typecheck)
(cd packages/dsh && npm ci && npm run typecheck && npm run build)
```

## Conventions

- **JSON on stdout, diagnostics on stderr.** Every command prints one JSON
  object (or JSON lines) so an agent can consume it. Keep the exit codes stable:
  `0` ok, `2` usage/permission/platform, `3` not found / stale ref / upstream
  error, `4` capture failed, `5` target changed, `6` refused by policy,
  `7` timeout. Failures use the envelope in `results.py`
  (`reason`, `action_sent`, `retry`).
- **Every input goes through `gate.check()`.** New mutating commands must call
  it (sensitive apps, secure input, locked screen, system chords, dry run) and
  log through `policy.audit()` with text redacted to its length.
- **Never claim success you did not verify.** Emitted-the-event (`action_sent`)
  and the-UI-changed (`verified`) are separate facts, and every fallback hint
  must follow from evidence.
- **No machine-specific defaults.** No absolute paths, no assumed display scale,
  no assumed app names. If a value depends on the machine, detect it or require
  it explicitly.
- **Pure logic stays pure.** Policy functions such as `jev.decide()` take values
  and return a decision, so they can be unit-tested without a desktop or a
  network.
- **Both bridges stay bridges.** The pi and dsh packages call the CLI with argv
  arrays and return its output; they must not grow a second implementation, and
  they must never use a shell string.
- **Keep the skill honest.** If a capability changes, update `skill/SKILL.md` —
  it is what agents actually read — then run `scripts/sync-skill.sh` to refresh
  the copies (CI fails on a stale copy).
- **Never leak what is on screen.** Secure fields stay redacted, typed text is
  never logged verbatim, and files the toolkit writes are private (`0600`).

## Adding a command

1. Implement it in the matching `src/macos_computer_use/*.py` module.
2. Wire it into `build_parser()` in `cli.py` and into the `doctor` hints if it
   needs a permission.
3. Add or extend a test when the logic is pure.
4. Expose it in `mcp_server.py` if agents should call it directly.
5. Update `README.md`, `README.zh-CN.md`, `skill/SKILL.md`, and (for a new
   desktop action) both bridge packages' tool lists.

## Reporting a computer-use bug

Include: the exact command, the JSON it returned, the app and its bundle id, the
macOS version, and whether the app was frontmost. If AX targeting failed, say
whether `verified` was false and whether the element is custom-drawn — that is
the difference between a bug here and an app that does not implement
accessibility.

## License

By contributing you agree your work is released under the MIT License.
