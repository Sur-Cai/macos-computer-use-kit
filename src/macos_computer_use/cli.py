"""Command line interface: ``macos-cu <group> <command> [options]``.

Every command prints JSON so an agent can consume it directly. Exit codes are
stable and meaningful:

- 0 success
- 2 usage error, unsupported platform, or missing permission
- 3 not found / capture failed / upstream HTTP error
- 4 target app not found (paste) or capture failed
- 5 target_changed (window signature mismatch) or paste conflict
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
    ax.add_argument("cmd", choices=["tree", "find", "click-info", "snapshot", "resolve", "press", "setvalue"])
    ax.add_argument("--app", default=None, help="app name or bundle id (substring match)")
    ax.add_argument("--pid", type=int, default=None, help="target a specific process instead of --app")
    ax.add_argument("--depth", type=int, default=16)
    ax.add_argument("--max", type=int, default=120, help="cap rows printed (tree/find)")
    ax.add_argument("--role", default=None, help="AX role filter, e.g. AXButton")
    ax.add_argument("--title", default=None, help="substring match on title/description/value")
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
    ax.add_argument("--id", default=None, help="element id inside a snapshot (for resolve)")
    ax.add_argument("--text", default=None, help="text to write (for setvalue)")

    # ------------------------------------------------------------- input
    inp = groups.add_parser("input", help="process/window-scoped input (the physical cursor never moves)")
    inp.add_argument("cmd", choices=["windows", "cursor", "pid", "click", "key", "scroll", "move"])
    inp.add_argument("--app")
    inp.add_argument("--pid", type=int)
    inp.add_argument("--window-id", type=int, help="target a window; --x/--y become window-relative")
    inp.add_argument("--expect", help="expected signature pid:wid:x:y:w:h; mismatch refuses with target_changed")
    inp.add_argument("--show", action="store_true", help="draw a visual ring at the action point")
    inp.add_argument("--x", type=int)
    inp.add_argument("--y", type=int)
    inp.add_argument("--button", default="left", choices=["left", "right", "middle"])
    inp.add_argument("--count", type=int, default=1)
    inp.add_argument("--key")
    inp.add_argument("--flags", default="", help="modifier flags, e.g. cmd+shift")
    inp.add_argument("--amount", type=int, default=-5, help="scroll lines: negative = up, positive = down")

    # ------------------------------------------------------------- paste
    paste = groups.add_parser("paste", help="clipboard-safe paste that restores the user's clipboard")
    paste.add_argument("--app")
    paste.add_argument("--pid", type=int)
    paste.add_argument("--text", required=True)
    paste.add_argument("--mode", choices=["pid", "hid"], default="pid",
                       help="pid = post to the app (cursor untouched); hid = system-wide")
    paste.add_argument("--wait", type=float, default=1.5, help="seconds to wait before checking consumption")
    paste.add_argument("--keep", action="store_true", help="leave our text on the clipboard")

    # -------------------------------------------------------------- shot
    shot = groups.add_parser("shot", help="screenshots with blank-frame detection")
    shot.add_argument("cmd", choices=["capture", "check", "windows"])
    shot.add_argument("--file")
    shot.add_argument("--out")
    shot.add_argument("--window-id", type=int)
    shot.add_argument("--app")
    shot.add_argument("--region", help="x,y,w,h")

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

    # ------------------------------------------------------------ doctor
    groups.add_parser("doctor", help="diagnose permissions, displays, dependencies, and Jev setup")

    return ap


def _pyobjc_version() -> str | None:
    try:
        import objc

        return getattr(objc, "__version__", None)
    except Exception:
        return None


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
        info["hints"].append("All checks passed. Try: macos-cu ax tree --app Finder --max 20")

    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if (perms.get("accessibility") and perms.get("screen_recording")) else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.group == "doctor":
        return doctor()

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
