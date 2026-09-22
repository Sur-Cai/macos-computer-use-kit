# Publishing this toolkit

> Maintainer document, public on purpose: a fork should be able to release under
> its own npm/PyPI names without reverse-engineering this layout. Nothing here is
> secret — no credentials, no private infrastructure, no deploy internals.

Three artifacts can be published from this repository, all versioned in lockstep
with the CLI (bump `pyproject.toml`, `packages/pi/package.json`, and
`packages/dsh/package.json` together):

| Artifact | Registry | Command |
| --- | --- | --- |
| `macos-computer-use-kit` | PyPI | `python -m build && twine upload dist/*` |
| `pi-macos-computer-use` | npm | `cd packages/pi && npm publish` |
| `dsh-macos-computer-use` | npm | `cd packages/dsh && npm publish` |

## Before the first publish

1. **Never commit a key.** The Jev key lives in `~/.config/typesafe/api_key` and
   the environment. Check `git status` and `git diff --cached` before pushing;
   `.gitignore` already excludes `node_modules/`, build output, and `*.png`.
2. **Bump all three versions together.** They are independent manifests:
   `pyproject.toml`, `packages/pi/package.json`, `packages/dsh/package.json`.
   `packages/pi/skills/macos-computer-use/SKILL.md` is a copy of `skill/SKILL.md`
   — refresh it (`cp skill/SKILL.md packages/pi/skills/macos-computer-use/SKILL.md`)
   and re-run `./install.sh` to refresh the opencode copy.
3. **Add GitHub topics** for discoverability (Repository → About → Topics):

   ```
   dsh-plugin  pi-package  macos  computer-use  accessibility
   ai-agents  agent-skills  gui-automation  opencode
   ```

   `dsh-plugin` is how <https://github.com/topics/dsh-plugin> indexes plugins;
   the `pi-package` npm keyword is what <https://pi.dev/packages> indexes.

## PyPI (the CLI)

```bash
python -m pip install --upgrade build twine
python -m build                       # sdist + wheel in dist/
twine check dist/*
twine upload dist/*                   # needs a PyPI API token
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
./install.sh                      # local sanity: CLI + skill
macos-cu doctor                   # permissions still granted after reinstalling
(cd packages/pi  && npm run typecheck)
(cd packages/dsh && npm run typecheck && npm run build)
```

Then tag (`git tag v<version> && git push --tags`) and publish the artifacts you
intend to ship.

## Current release state

| Artifact | Published | Notes |
| --- | --- | --- |
| `macos-computer-use-kit` | PyPI `0.2.2` | `pip install macos-computer-use-kit` |
| `pi-macos-computer-use` | npm `0.2.2` | listed on pi.dev/packages |
| `dsh-macos-computer-use` | npm `0.2.2` | 6 tools; awesome-dsh-plugin PR pending |

Discoverability keywords are part of the release, not an edit: npm and PyPI
metadata is immutable per version, so adding `jev` / `typesafe-ai` /
`system-one-models` required cutting 0.2.2. Keep that in mind when tweaking
keywords — batch them with something else.

Known follow-ups: the awesome-dsh-plugin catalog PR is gated on the 1-day
repository-age rule (earliest 2026-09-23T10:22Z).
