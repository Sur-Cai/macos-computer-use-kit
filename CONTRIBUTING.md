# Contributing

Bug reports, platform findings, and pull requests are welcome. This toolkit
drives real desktops, so evidence beats opinion: paste the JSON a command
returned, the macOS version, and the app you were driving.

## Layout

```
src/macos_computer_use/   the CLI (single source of truth)
tools/*.py                compatibility shims over the same modules
skill/                    agent skill + Jev reference
packages/pi/              pi package (skill + tools; sources, no build)
packages/dsh/             DeepSeek Harness bundle (TypeScript -> lib/)
tests/                    unit tests for pure logic
```

## Develop

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
macos-cu doctor

(cd packages/pi  && npm ci && npm run typecheck)
(cd packages/dsh && npm ci && npm run typecheck && npm run build)
```

## Conventions

- **JSON on stdout, diagnostics on stderr.** Every command prints one JSON
  object (or JSON lines) so an agent can consume it. Keep the exit codes stable:
  `0` ok, `2` usage/permission/platform, `3` not found or upstream error,
  `4` capture failed, `5` target changed.
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
  it is what agents actually read. `packages/pi/skills/...` mirrors it.

## Adding a command

1. Implement it in the matching `src/macos_computer_use/*.py` module.
2. Wire it into `build_parser()` in `cli.py` and into the `doctor` hints if it
   needs a permission.
3. Add or extend a test when the logic is pure.
4. Update `README.md`, `skill/SKILL.md`, and (for a new desktop action) both
   bridge packages' tool lists.

## Reporting a computer-use bug

Include: the exact command, the JSON it returned, the app and its bundle id, the
macOS version, and whether the app was frontmost. If AX targeting failed, say
whether `verified` was false and whether the element is custom-drawn — that is
the difference between a bug here and an app that does not implement
accessibility.

## License

By contributing you agree your work is released under the MIT License.
