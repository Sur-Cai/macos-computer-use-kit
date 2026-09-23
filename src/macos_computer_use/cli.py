"""Command line interface: ``macos-cu <group> <command> [options]``.

Every command prints JSON so an agent can consume it directly. Exit codes are
stable and meaningful:

- 0 success
- 2 usage error, unsupported platform, or missing permission
- 3 not found (element / app / text / stale ref) or upstream HTTP error
- 4 capture failed, or target app not found (paste)
- 5 target_changed (window signature mismatch) or paste conflict
- 6 refused by the safety policy (sensitive app, secure input, system chord)
- 7 timed out (``ax wait``)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import __version__, darwin

EXIT_USAGE = 2


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="emit structured JSON (where the command has a text mode)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="macos-cu",
        description="AX-first computer-use toolkit for macOS agents.",
        epilog="Run `macos-cu doctor` first to check permissions and display geometry.",
    )
    ap.add_argument("--version", action="version", version=f"macos-computer-use-kit {__version__}")
    groups = ap.add_subparsers(dest="group", required=True)

    # ---------------------------------------------------------------- ax
    ax = groups.add_parser("ax", help="read the accessibility tree and run native AX actions")
    _add_common(ax)
    ax.add_argument(
        "cmd",
        choices=["tree", "find", "click-info", "snapshot", "resolve", "press", "setvalue", "action", "actions",
                 "focus", "at", "wait"],
    )
    ax.add_argument("--app", default=None, help="app name or bundle id (exact match preferred, then substring)")
    ax.add_argument("--pid", type=int, default=None, help="target a specific process instead of --app")
    ax.add_argument("--depth", type=int, default=16)
    ax.add_argument("--max", type=int, default=120, help="cap rows printed (tree/find)")
    ax.add_argument("--role", default=None, help="AX role filter, e.g. AXButton")
    ax.add_argument("--title", default=None, help="substring match on title/description/value")
    ax.add_argument("--ref", default=None, help="stable element ref from a snapshot (press/setvalue/action/wait)")
    ax.add_argument("--interactive", action="store_true", help="only actionable elements (buttons, fields, ...)")
    ax.add_argument("--index", type=int, default=None, help="element index for click-info")
    ax.add_argument(
        "--shot-scale",
        type=float,
        default=None,
        help="also emit center_shot = round(center_screen * SCALE). Only needed when your harness's "
        "screenshots use a different scale than screen points; there is no safe default.",
    )
    ax.add_argument("--budget", type=int, default=4000, help="max characters of snapshot text")
    ax.add_argument("--file", default=None, help="snapshot cache file (for resolve)")
    ax.add_argument("--file-out", default=None, help="where snapshot writes its cache (default: cache dir)")
    ax.add_argument("--diff", default=None, help="snapshot: diff against this earlier snapshot file")
    ax.add_argument("--id", default=None, help="element path id inside a snapshot (for resolve)")
    ax.add_argument("--text", default=None, help="text to write (for setvalue)")
    ax.add_argument("--name", default=None, help="AX action name for `ax action`, e.g. AXShowMenu, AXIncrement")
    ax.add_argument("--x", type=float, help="screen x for `ax at`")
    ax.add_argument("--y", type=float, help="screen y for `ax at`")
    ax.add_argument("--value", default=None, help="wait: element value must contain this")
    ax.add_argument("--gone", action="store_true", help="wait: until the element disappears")
    ax.add_argument("--timeout", type=float, default=10.0, help="wait: seconds")
    ax.add_argument("--interval", type=float, default=0.4, help="wait: poll interval seconds")

    # ------------------------------------------------------------- input
    inp = groups.add_parser("input", help="process/window-scoped input (the physical cursor never moves)")
    inp.add_argument("cmd", choices=["windows", "cursor", "pid", "click", "key", "type", "scroll", "move", "hover",
                                     "drag"])
    inp.add_argument("--app")
    inp.add_argument("--pid", type=int)
    inp.add_argument("--window-id", type=int, help="target a window; --x/--y become window-relative")
    inp.add_argument("--expect", help="expected signature pid:wid:x:y:w:h; mismatch refuses with target_changed")
    inp.add_argument("--show", action="store_true", help="draw a visual ring at the action point")
    inp.add_argument("--x", type=int)
    inp.add_argument("--y", type=int)
    inp.add_argument("--to-x", type=int, help="drag destination x")
    inp.add_argument("--to-y", type=int, help="drag destination y")
    inp.add_argument("--steps", type=int, default=12, help="drag: intermediate points")
    inp.add_argument("--button", default="left", choices=["left", "right", "middle"])
    inp.add_argument("--count", type=int, default=1, help="click count: 2 = double, 3 = triple")
    inp.add_argument("--key", help="key or chord: return, cmd+l, cmd+shift+t, mod+s, f5, ...")
    inp.add_argument("--flags", default="", help="extra modifier flags, e.g. cmd+shift (also for click)")
    inp.add_argument("--repeat", type=int, default=1, help="key: press N times")
    inp.add_argument("--text", help="type: Unicode text (CJK/emoji safe, clipboard untouched)")
    inp.add_argument("--amount", type=int, default=5, help="scroll: positive = down, negative = up")
    inp.add_argument("--dx", type=int, default=0, help="scroll: positive = right, negative = left")
    inp.add_argument("--unit", default="line", choices=["line", "pixel"], help="scroll unit")
    inp.add_argument("--mode", default="pid", choices=["pid", "hid"],
                     help="pid = post to the app (cursor untouched); hid = system-wide (moves the real cursor)")

    # ------------------------------------------------------------- paste
    paste = groups.add_parser("paste", help="clipboard-safe paste that restores the user's clipboard")
    paste.add_argument("--app")
    paste.add_argument("--pid", type=int)
    paste.add_argument("--text", required=True)
    paste.add_argument("--mode", choices=["pid", "hid"], default="pid",
                       help="pid = post to the app (cursor untouched); hid = system-wide")
    paste.add_argument("--wait", type=float, default=1.5, help="seconds to wait before checking consumption")
    paste.add_argument("--keep", action="store_true", help="leave our text on the clipboard")

    # --------------------------------------------------------------- app
    app = groups.add_parser("app", help="list / launch / activate / hide / quit apps; open URLs and files")
    app.add_argument("cmd", choices=["list", "launch", "activate", "hide", "quit", "open"])
    app.add_argument("--app")
    app.add_argument("--pid", type=int)
    app.add_argument("--target", help="open: URL or file path")
    app.add_argument("--background", action="store_true", help="launch/open without activating")
    app.add_argument("--force", action="store_true", help="quit: force terminate")
    app.add_argument("--all", action="store_true", help="list: include background / menu-bar agents")

    # ------------------------------------------------------------ window
    win = groups.add_parser("window", help="move / resize / minimize / raise / focus / close windows via AX")
    win.add_argument("cmd", choices=["list", "move", "resize", "minimize", "restore", "raise", "focus", "close",
                                     "fullscreen"])
    win.add_argument("--app")
    win.add_argument("--pid", type=int)
    win.add_argument("--title", help="window title substring (default: focused window)")
    win.add_argument("--index", type=int, help="window index from `window list`")
    win.add_argument("--x", type=int)
    win.add_argument("--y", type=int)
    win.add_argument("--width", type=int)
    win.add_argument("--height", type=int)

    # -------------------------------------------------------------- menu
    menu = groups.add_parser("menu", help="walk the menu bar by path, e.g. 'File > Export…'")
    menu.add_argument("cmd", choices=["list", "select"])
    menu.add_argument("--app")
    menu.add_argument("--pid", type=int)
    menu.add_argument("--path", default="", help="menu path separated by '>'")

    # -------------------------------------------------------------- shot
    shot = groups.add_parser("shot", help="screenshots with blank-frame detection and set-of-mark labels")
    shot.add_argument("cmd", choices=["capture", "check", "windows", "displays", "annotate"])
    shot.add_argument("--file")
    shot.add_argument("--out")
    shot.add_argument("--window-id", type=int)
    shot.add_argument("--app")
    shot.add_argument("--pid", type=int)
    shot.add_argument("--region", help="x,y,w,h in screen points")
    shot.add_argument("--display", type=int, help="display index (see `shot displays`)")
    shot.add_argument("--crop", help="x,y,w,h in screen points to cut out of the capture (zoom)")
    shot.add_argument("--max", type=int, default=80, help="annotate: max marks")
    shot.add_argument("--base64", action="store_true", help="include the PNG inline as base64")
    shot.add_argument("--max-width", type=int, default=None, help="downscale the inline image to this width")

    # --------------------------------------------------------------- ocr
    ocr = groups.add_parser("ocr", help="on-device Vision OCR with screen coordinates (fallback when AX is empty)")
    ocr.add_argument("--file", help="OCR an existing image instead of capturing")
    ocr.add_argument("--origin", help="with --file: screen point of the image's top-left, 'x,y'")
    ocr.add_argument("--scale", type=float, help="with --file: image pixels per screen point")
    ocr.add_argument("--app")
    ocr.add_argument("--window-id", type=int)
    ocr.add_argument("--region", help="x,y,w,h in screen points")
    ocr.add_argument("--text", help="only return items containing this text")
    ocr.add_argument("--exact", action="store_true", help="with --text: whole-string match")
    ocr.add_argument("--lang", help="recognition languages, e.g. zh-Hans,en-US")
    ocr.add_argument("--fast", action="store_true", help="fast recognizer (lower accuracy)")
    ocr.add_argument("--max", type=int, default=200)
    ocr.add_argument("--keep", action="store_true", help="keep the captured image")

    # ----------------------------------------------------------- overlay
    overlay = groups.add_parser("overlay", help="transient visual feedback ring")
    overlay.add_argument("cmd", choices=["show", "clear"])
    overlay.add_argument("--x", type=int)
    overlay.add_argument("--y", type=int)
    overlay.add_argument("--label", default="")
    overlay.add_argument("--duration", type=float, default=1.5)
    overlay.add_argument("--color", default="cyan", choices=["cyan", "green", "orange", "red"])

    # --------------------------------------------------------------- jev
    jev = groups.add_parser("jev", help="optional TypeSafe System One semantic guards (JSON on stdin)")
    jev.add_argument("cmd", choices=["guard", "select"])

    # --------------------------------------------------------------- mcp
    mcp = groups.add_parser("mcp", help="run the MCP server on stdio (Claude Code, Codex, Cursor, ...)")
    mcp.add_argument("--read-only", action="store_true", help="expose observation tools only")
    mcp.add_argument("--tools", help="comma-separated allowlist of tool names")
    mcp.add_argument("--exclude-tools", help="comma-separated denylist of tool names")
    mcp.add_argument("--list-tools", action="store_true", help="print the tool list as JSON and exit")

    # ------------------------------------------------------------- setup
    setup = groups.add_parser("setup", help="register the MCP server / skill with an agent client")
    setup.add_argument("client", choices=["claude-code", "claude-desktop", "codex", "cursor", "gemini", "opencode",
                                          "skill", "print"])
    setup.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    setup.add_argument("--read-only", action="store_true", help="register the read-only tool set")
    setup.add_argument("--scope", default="user", choices=["user", "project", "local"],
                       help="claude-code scope (default user)")

    # ------------------------------------------------------------ doctor
    groups.add_parser("doctor", help="diagnose permissions, displays, dependencies, and Jev setup")

    return ap


def _pyobjc_version() -> str | None:
    try:
        import objc

        return getattr(objc, "__version__", None)
    except Exception:
        return None


def _ocr_available() -> bool:
    try:
        from . import ocr

        return ocr.available()
    except Exception:
        return False


def _policy_summary() -> dict[str, Any]:
    from . import policy

    return {
        "dry_run": policy.dry_run(),
        "audit": os.environ.get("MACOS_CU_AUDIT", "") not in ("", "0"),
        "audit_log": policy.audit_path(),
        "allow_apps": os.environ.get("MACOS_CU_ALLOW_APPS") or None,
        "deny_apps": os.environ.get("MACOS_CU_DENY_APPS") or None,
        "sensitive_apps_blocked": os.environ.get("MACOS_CU_ALLOW_SENSITIVE", "") in ("", "0"),
    }


def doctor() -> int:
    perms = {"accessibility": False, "screen_recording": False}
    perm_error = None
    try:
        perms = darwin.permissions()
    except SystemExit as exc:  # dependency missing
        perm_error = str(exc.code)

    info: dict[str, Any] = {
        "version": __version__,
        "platform": {"system": sys.platform, "macos": darwin.macos_version(), "arch": os.uname().machine},
        "python": sys.version.split()[0],
        "pyobjc": _pyobjc_version(),
        "permissions": perms,
        "displays": [],
        "jev": {"key_present": bool(darwin.jev_key()), "model": os.environ.get("TYPESAFE_MODEL", "jev-latest")},
        "ocr": {"vision": _ocr_available()},
        "policy": _policy_summary(),
        "hints": [],
    }
    try:
        info["displays"] = darwin.displays()
    except Exception as exc:  # pragma: no cover - defensive
        info["displays_error"] = str(exc)[:200]

    if perm_error:
        info["hints"].append("Install dependencies: pip install 'macos-computer-use-kit'")
    else:
        if not perms.get("accessibility"):
            info["hints"].append(darwin.permission_hint("accessibility"))
        if not perms.get("screen_recording"):
            info["hints"].append(darwin.permission_hint("screen_recording"))
    if not info["jev"]["key_present"]:
        info["hints"].append(
            "Jev is optional. To enable semantic guards, set TYPESAFE_API_KEY or write "
            "~/.config/typesafe/api_key (https://console.typesafe.ai/keys)."
        )
    if not info["hints"]:
        info["hints"].append("All checks passed. Try: macos-cu ax snapshot --app Finder --interactive")
    info["next"] = "Register with your agent: macos-cu setup claude-code | codex | cursor | claude-desktop"

    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if (perms.get("accessibility") and perms.get("screen_recording")) else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.group == "doctor":
        return doctor()
    if args.group == "setup":
        from . import setup

        return setup.run(args)
    if args.group == "mcp":
        from . import mcp_server

        if args.list_tools:
            tools = mcp_server.select_tools(args.read_only, args.tools, args.exclude_tools)
            print(json.dumps([t.spec() for t in tools], ensure_ascii=False, indent=2))
            return 0
        return mcp_server.serve(args.read_only, args.tools, args.exclude_tools)

    darwin.require_macos()

    if args.group == "ax":
        from . import ax

        return ax.run(args)
    if args.group == "input":
        from . import input_events

        return input_events.run(args)
    if args.group == "paste":
        from . import paste

        return paste.run(args)
    if args.group in ("app", "window", "menu"):
        from . import apps

        return apps.run(args)
    if args.group == "ocr":
        from . import ocr

        return ocr.run(args)
    if args.group == "shot":
        from . import shot

        return shot.run(args)
    if args.group == "overlay":
        from . import overlay

        return overlay.run(args)
    if args.group == "jev":
        from . import jev

        return jev.run(args)

    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
