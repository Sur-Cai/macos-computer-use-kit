# Publishing this toolkit

> Maintainer document, public on purpose: a fork should be able to release under
> its own npm/PyPI names without reverse-engineering this layout. Nothing here is
> secret — no credentials, no private infrastructure, no deploy internals.

Three registry artifacts can be published from this repository, plus the
Claude Code plugin that is served straight from the git repo. All are versioned
in lockstep; `tests/test_v03.py::TestVersionLockstep` fails if they drift:

| Artifact | Registry | Command |
| --- | --- | --- |
| `macos-computer-use-kit` | PyPI | `python -m build && twine upload dist/*` |
| `pi-macos-computer-use` | npm | `cd packages/pi && npm publish` |
| `dsh-macos-computer-use` | npm | `cd packages/dsh && npm publish` |
| `macos-computer-use` plugin | git (Claude Code marketplace) | push to `main`; users run `/plugin marketplace add Sur-Cai/macos-computer-use-kit` |

## Before the first publish

1. **Never commit a key.** The Jev key lives in `~/.config/typesafe/api_key` and
   the environment. Check `git status` and `git diff --cached` before pushing;
   `.gitignore` already excludes `node_modules/`, build output, and `*.png`.
2. **Bump every version together.** The manifests are independent:
   `pyproject.toml`, `src/macos_computer_use/__init__.py`,
   `packages/pi/package.json`, `packages/dsh/package.json`,
   `plugins/claude-code/.claude-plugin/plugin.json` and the plugin entry in
   `.claude-plugin/marketplace.json`. The skill copies are refreshed with
   `scripts/sync-skill.sh`.
3. **Add GitHub topics** for discoverability (Repository → About → Topics):

   ```
   mcp  mcp-server  claude-code  computer-use  macos  accessibility
   ai-agents  agent-skills  gui-automation  desktop-automation  ocr
   dsh-plugin  pi-package  opencode
   ```

   `dsh-plugin` is how <https://github.com/topics/dsh-plugin> indexes plugins;
   the `pi-package` npm keyword is what <https://pi.dev/packages> indexes.

## PyPI (the CLI)

```bash
python -m pip install --upgrade build twine
python -m build                       # sdist + wheel in dist/
twine check dist/*
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" twine upload dist/*
```

Verify the install path in a clean venv before tagging:

```bash
python -m venv /tmp/verify && /tmp/verify/bin/pip install dist/*.whl
/tmp/verify/bin/macos-cu doctor
```

## npm: the pi package

```bash
cd packages/pi
npm run typecheck
npm pack --dry-run                    # confirm the tarball contents
npm publish                           # unscoped; use --access public inside a scope
```

The `pi` manifest (`extensions`, `skills`) plus the `pi-package` keyword are what
make the catalog pick it up. The extension is loaded through pi's TypeScript
loader, so it ships sources — no build step, and `peerDependencies` stay `"*"`.

## npm: the dsh bundle

```bash
cd packages/dsh
npm run build                         # emits lib/ ; `prepare` runs this on git installs
npm pack --dry-run
npm publish
```

The bundle contract is `dsh.bundle.patch` → `cordis.patch.yml`. Because git
installs fetch **sources**, the `prepare` script must stay self-contained (no
monorepo project references); publishing a tarball or npm package ships the
built `lib/` and needs no build permission from the user.

Users install with:

```bash
dsh plugin --profile <name> add dsh-macos-computer-use        # from npm (recommended)
dsh plugin --profile <name> add ./dsh-macos-computer-use-<version>.tgz   # from a packed tarball
```

The npm and tarball forms ship the prebuilt `lib/`, so no build permission is
needed. Installing straight from git fetches sources and runs `prepare`, which
pnpm blocks until the user allowlists it — and because the bundle lives in
`packages/dsh/` of this monorepo, the git form is only convenient for a repo
that root-mounts the package. Prefer npm or the tarball for distribution.

## Catalog listings

- **pi**: publishing to npm is enough — the gallery at <https://pi.dev/packages>
  lists packages tagged `pi-package`. This is confirmed working: the page for
  `pi-macos-computer-use` appeared shortly after the npm publish. Optionally add
  a `pi.image` or `pi.video` preview to `packages/pi/package.json` for a richer
  card.
- **dsh**: add the `dsh-plugin` GitHub topic, then open a PR against
  [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin).
  Submissions are **one YAML file per plugin** under `data/plugins/` — never edit
  the generated READMEs. For this monorepo the file is
  `data/plugins/Sur-Cai__macos-computer-use-kit--packages-dsh.yml`, with `url`
  pointing at `.../tree/main/packages/dsh` and `name` written as
  `Sur-Cai/macos-computer-use-kit#packages/dsh`.

  Their CI enforces a **1-day minimum repository age** (ours was created
  2026-09-22T10:22Z, so the earliest valid submission is the next day at the same
  time) and at most 3 entries per PR. Descriptions are checked against the code,
  so keep numbers and tool names exact. There is also
  [dsh-market](https://github.com/dsh-market/dsh-market) for in-app discovery.

## Release checklist

```bash
pytest -q
scripts/sync-skill.sh --check
claude plugin validate . && claude plugin validate plugins/claude-code
macos-cu mcp --list-tools         # 18 tools
macos-cu doctor                   # permissions still granted after reinstalling
(cd packages/pi  && npm ci && npm run typecheck)
(cd packages/dsh && npm ci && npm run typecheck && npm run build)
```

Tokens come from the environment for the one command that needs them
(`TWINE_PASSWORD`, `NODE_AUTH_TOKEN` via a temporary `.npmrc` outside the repo).
Never write them into the repository, and revoke any token that was pasted into
a chat or a log.

Then tag (`git tag v<version> && git push --tags`) and publish the artifacts you
intend to ship.

## Current release state

| Artifact | Published | Notes |
| --- | --- | --- |
| `macos-computer-use-kit` | PyPI `0.2.2` (0.3.0 prepared) | `pip install macos-computer-use-kit` |
| `pi-macos-computer-use` | npm `0.2.2` (0.3.0 prepared) | listed on pi.dev/packages |
| `dsh-macos-computer-use` | npm `0.2.2` (0.3.0 prepared) | 11 tools in 0.3.0; awesome-dsh-plugin PR pending |
| Claude Code plugin | new in 0.3.0 | served from this repository |

Discoverability keywords are part of the release, not an edit: npm and PyPI
metadata is immutable per version, so adding `jev` / `typesafe-ai` /
`system-one-models` required cutting 0.2.2. Keep that in mind when tweaking
keywords — batch them with something else.

Known follow-ups: the awesome-dsh-plugin catalog PR is gated on the 1-day
repository-age rule (earliest 2026-09-23T10:22Z).
