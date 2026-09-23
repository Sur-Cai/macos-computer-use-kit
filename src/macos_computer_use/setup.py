"""``macos-cu setup <client>``: register the MCP server (and skill) with agents.

One command per client, idempotent, with ``--dry-run``. JSON config files are
merged (other servers are preserved) and backed up to ``<file>.bak`` before the
first write. Where a client ships its own CLI (``claude mcp add``, ``codex mcp
add``) that CLI is used, so the client stays the owner of its config format.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "macos-computer-use"
PACKAGE = "macos-computer-use-kit"


def server_command(read_only: bool = False) -> list[str]:
    """The argv a client should spawn. Absolute paths: GUI apps have no shell PATH."""
    extra = ["--read-only"] if read_only else []
    override = os.environ.get("MACOS_CU_BIN")
    if override:
        return [override, "mcp", *extra]
    ephemeral = any(part in sys.prefix for part in ("/uv/archive", "/.cache/uv/", "/pipx/.cache/"))
    if not ephemeral:
        found = shutil.which("macos-cu")
        if found:
            return [found, "mcp", *extra]
        candidate = Path(sys.executable).with_name("macos-cu")
        if candidate.exists():
            return [str(candidate), "mcp", *extra]
    uvx = shutil.which("uvx")
    if uvx:
        return [uvx, PACKAGE, "mcp", *extra]
    return ["macos-cu", "mcp", *extra]


def merge_server(config: dict[str, Any], entry: dict[str, Any], key: str = "mcpServers",
                 name: str = SERVER_NAME) -> tuple[dict[str, Any], bool]:
    """Pure: return ``(new_config, changed)`` with ``entry`` under ``config[key][name]``."""
    new = json.loads(json.dumps(config)) if config else {}
    servers = new.setdefault(key, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{key} in the existing config is not an object")
    changed = servers.get(name) != entry
    servers[name] = entry
    return new, changed


def _write_json(path: Path, key: str, entry: dict[str, Any], dry: bool) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            try:
                existing = json.loads(text)
            except ValueError as exc:
                return {"ok": False, "reason": "config_not_json", "path": str(path), "detail": str(exc)[:200],
                        "hint": "fix or move the file, then rerun"}
    try:
        new, changed = merge_server(existing, entry, key)
    except ValueError as exc:
        return {"ok": False, "reason": "config_shape", "path": str(path), "detail": str(exc)}
    if dry or not changed:
        return {"ok": True, "path": str(path), "changed": changed, "dry_run": dry, "entry": entry}
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.with_suffix(path.suffix + ".bak").exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "changed": True, "entry": entry}


def _run(argv: list[str], dry: bool) -> dict[str, Any]:
    if dry:
        return {"ok": True, "dry_run": True, "command": argv}
    proc = subprocess.run(argv, capture_output=True, text=True)
    out = {"ok": proc.returncode == 0, "command": argv, "stdout": proc.stdout.strip()[-400:],
           "stderr": proc.stderr.strip()[-400:]}
    if not out["ok"] and "already exists" in (proc.stderr + proc.stdout):
        out.update(ok=True, changed=False, note="already registered")
    return out


def skill_source() -> Path | None:
    """The bundled skill directory (wheel) or the checkout's ``skill/``."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "_skill", here.parents[1] / "skill"):
        if (candidate / "SKILL.md").exists():
            return candidate
    return None


def install_skill(dest: Path, dry: bool) -> dict[str, Any]:
    src = skill_source()
    if src is None:
        return {"ok": False, "reason": "skill_not_bundled"}
    if not dry:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    return {"ok": True, "skill": str(dest), "dry_run": dry}


def setup(client: str, dry: bool = False, read_only: bool = False, scope: str = "user") -> dict[str, Any]:
    cmd = server_command(read_only)
    home = Path.home()
    stdio = {"command": cmd[0], "args": cmd[1:]}

    if client == "print":
        return {
            "ok": True,
            "command": cmd,
            "mcpServers": {SERVER_NAME: stdio},
            "claude_code": ["claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--", *cmd],
            "codex": ["codex", "mcp", "add", SERVER_NAME, "--", *cmd],
        }

    if client == "claude-code":
        claude = shutil.which("claude")
        argv = ["claude", "mcp", "add", "--scope", scope, SERVER_NAME, "--", *cmd]
        if claude is None:
            return {"ok": False, "reason": "claude_cli_not_found", "run_this": argv,
                    "hint": "or install the Claude Code plugin: /plugin marketplace add Sur-Cai/macos-computer-use-kit"}
        result = _run([claude, *argv[1:]], dry)
        result["skill"] = install_skill(home / ".claude" / "skills" / SERVER_NAME, dry)
        return result

    if client == "codex":
        codex = shutil.which("codex")
        if codex:
            result = _run([codex, "mcp", "add", SERVER_NAME, "--", *cmd], dry)
        else:
            result = _codex_toml(home / ".codex" / "config.toml", cmd, dry)
        result["skill"] = install_skill(home / ".codex" / "skills" / SERVER_NAME, dry)
        return result

    if client == "claude-desktop":
        path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        result = _write_json(path, "mcpServers", stdio, dry)
        result["next"] = "quit and reopen Claude Desktop, then grant it Accessibility + Screen Recording"
        return result

    if client == "cursor":
        return _write_json(home / ".cursor" / "mcp.json", "mcpServers", stdio, dry)

    if client == "gemini":
        return _write_json(home / ".gemini" / "settings.json", "mcpServers", stdio, dry)

    if client == "opencode":
        base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode"
        result = _write_json(base / "opencode.json", "mcp", {"type": "local", "command": cmd, "enabled": True}, dry)
        result["skill"] = install_skill(base / "skills" / SERVER_NAME, dry)
        return result

    if client == "skill":
        targets = {
            "claude": home / ".claude" / "skills" / SERVER_NAME,
            "codex": home / ".codex" / "skills" / SERVER_NAME,
            "opencode": Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode" / "skills" / SERVER_NAME,
        }
        return {"ok": True, "installed": {k: install_skill(v, dry) for k, v in targets.items()}}

    return {"ok": False, "reason": "unknown_client", "client": client}


def codex_toml_block(cmd: list[str]) -> str:
    """Pure: the ``[mcp_servers.<name>]`` TOML block for Codex."""
    return (
        f"\n[mcp_servers.{SERVER_NAME}]\n"
        f"command = {json.dumps(cmd[0])}\n"
        f"args = {json.dumps(cmd[1:])}\n"
    )


def _codex_toml(path: Path, cmd: list[str], dry: bool) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if f"[mcp_servers.{SERVER_NAME}]" in text or f'[mcp_servers."{SERVER_NAME}"]' in text:
        return {"ok": True, "path": str(path), "changed": False, "note": "already registered; edit the file to change it"}
    block = codex_toml_block(cmd)
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(block)
    return {"ok": True, "path": str(path), "changed": True, "dry_run": dry, "appended": block}


def run(args) -> int:
    result = setup(args.client, args.dry_run, args.read_only, args.scope)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2
