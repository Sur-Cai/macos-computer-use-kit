#!/usr/bin/env bash
# Install the macOS computer-use kit for local agents.
#
#   ./install.sh                          # install the CLI + skill
#   TYPESAFE_API_KEY=apikey_... ./install.sh   # also configure the optional Jev key
#
# Idempotent: re-run after `git pull` to refresh the CLI and the skill.
#
# Install locations (override with env vars):
#   CLI venv      ${MACOS_CU_HOME:-$HOME/.local/share/macos-computer-use}/venv
#   CLI launcher  ~/.local/bin/macos-cu
#   Agent skill   ${OPENCODE_SKILLS_DIR:-$HOME/.config/opencode/skills}/macos-computer-use
#   Jev key       ~/.config/typesafe/api_key
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CU_HOME="${MACOS_CU_HOME:-$HOME/.local/share/macos-computer-use}"
BIN_DIR="${MACOS_CU_BIN_DIR:-$HOME/.local/bin}"
SKILL_DIR="${OPENCODE_SKILLS_DIR:-$HOME/.config/opencode/skills}/macos-computer-use"
TYPE_KEY_FILE="$HOME/.config/typesafe/api_key"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }

if [ "$(uname -s)" != "Darwin" ]; then
  warn "this toolkit is macOS-only (Accessibility + CoreGraphics APIs)"
  exit 1
fi

# ---------------------------------------------------------------- python + venv
pick_python() {
  for p in python3.13 python3.12 python3.14 python3; do
    command -v "$p" >/dev/null 2>&1 && { echo "$p"; return; }
  done
  return 1
}
PY="$(pick_python)" || { warn "python3 (>=3.10) not found; install Python first"; exit 1; }
say "python: $("$PY" -V 2>&1)"

mkdir -p "$CU_HOME"
[ -d "$CU_HOME/venv" ] || { say "creating venv at $CU_HOME/venv"; "$PY" -m venv "$CU_HOME/venv"; }
VENV="$CU_HOME/venv/bin/python"

say "installing the macos-cu package (first run downloads ~50 MB of pyobjc)"
# Pick whichever package index answers faster, so this works on any network
# without hardcoding a mirror.
choose_index() {
  local pypi mirror
  pypi=$(curl -s -o /dev/null -w '%{time_total}' --max-time 6 https://pypi.org/simple/pip/ 2>/dev/null || echo 99)
  mirror=$(curl -s -o /dev/null -w '%{time_total}' --max-time 6 https://pypi.tuna.tsinghua.edu.cn/simple/pip/ 2>/dev/null || echo 99)
  if awk "BEGIN{exit !($mirror < $pypi)}"; then
    echo "https://pypi.tuna.tsinghua.edu.cn/simple"
  fi
}
INDEX="$(choose_index || true)"
if [ -n "$INDEX" ]; then
  say "using mirror index $INDEX (faster than PyPI from here)"
fi
pip_install() {
  "$VENV" -m pip install --quiet --upgrade pip 2>/dev/null || true
  "$VENV" -m pip install --quiet --retries 5 --timeout 60 ${INDEX:+-i "$INDEX"} "$@"
}
# Prefer an editable install from this checkout so `git pull` updates take effect.
pip_install -e "$REPO" || pip_install "$REPO"

# ------------------------------------------------------------------- launcher
mkdir -p "$BIN_DIR"
ln -sf "$CU_HOME/venv/bin/macos-cu" "$BIN_DIR/macos-cu"
say "launcher: $BIN_DIR/macos-cu"
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) warn "$BIN_DIR is not on PATH; add: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

# ---------------------------------------------------------------------- skill
install_skill() {
  local dest="$1"
  mkdir -p "$dest/reference"
  cp "$REPO/skill/SKILL.md" "$dest/SKILL.md"
  cp "$REPO/skill/reference/"*.md "$dest/reference/" 2>/dev/null || true
}
install_skill "$SKILL_DIR"
say "opencode skill: $SKILL_DIR (id: macos-computer-use)"
if [ -d "$HOME/.claude/skills" ]; then
  install_skill "$HOME/.claude/skills/macos-computer-use"
  say "also installed for Claude-style skill discovery"
fi

# ------------------------------------------------------------------------ jev
mkdir -p "$HOME/.config/typesafe" && chmod 700 "$HOME/.config/typesafe"
if [ -n "${TYPESAFE_API_KEY:-}" ]; then
  printf '%s\n' "$TYPESAFE_API_KEY" > "$TYPE_KEY_FILE"
  chmod 600 "$TYPE_KEY_FILE"
  say "Jev key written to $TYPE_KEY_FILE"
elif [ -s "$TYPE_KEY_FILE" ]; then
  say "Jev key already present at $TYPE_KEY_FILE"
else
  warn "no Jev key (optional). Set TYPESAFE_API_KEY=... or write $TYPE_KEY_FILE"
  warn "to enable semantic guards: https://console.typesafe.ai/keys"
fi

# --------------------------------------------------------------------- verify
say "checking environment"
set +e
"$CU_HOME/venv/bin/macos-cu" doctor
PERM=$?
set -e
if [ "$PERM" -ne 0 ]; then
  warn "grant Accessibility + Screen Recording to the process that runs the agent"
  warn "then re-run: macos-cu doctor"
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
fi

cat <<EOF

Done.

  macos-cu doctor
  macos-cu ax find --app Finder --role AXButton --json
  macos-cu input windows --app "Google Chrome"
  macos-cu shot capture --app "Google Chrome" --out /tmp/shot.png

Optional integrations:
  pi   : pi install npm:pi-macos-computer-use
  dsh  : dsh plugin --profile <name> add dsh-macos-computer-use
  (both live in ./packages/ and bridge to this same CLI)
EOF
