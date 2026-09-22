"""Process- and window-scoped input for macOS.

Delivers mouse/keyboard events straight to a target process's event queue with
``CGEventPostToPid``, so the system cursor never moves and the user's physical
mouse is untouched. Window-scoped actions take window-relative coordinates and
can validate a target signature before acting, which turns "the window moved
while I was aiming" into an explicit ``target_changed`` refusal instead of a
misclick.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from . import darwin


def _q():
    _AS, _NSWorkspace, Quartz = darwin._pyobjc()  # noqa: N806
    return Quartz


BUTTONS = {
    "left": ("kCGEventLeftMouseDown", "kCGEventLeftMouseUp", "kCGMouseButtonLeft"),
    "right": ("kCGEventRightMouseDown", "kCGEventRightMouseUp", "kCGMouseButtonRight"),
    "middle": ("kCGEventOtherMouseDown", "kCGEventOtherMouseUp", "kCGMouseButtonCenter"),
}

KEYS = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53, "esc": 53,
    "left": 123, "right": 124, "down": 125, "up": 126, "home": 115, "end": 119,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
}

FLAGS = {
    "cmd": "kCGEventFlagMaskCommand",
    "command": "kCGEventFlagMaskCommand",
    "shift": "kCGEventFlagMaskShift",
    "ctrl": "kCGEventFlagMaskControl",
    "control": "kCGEventFlagMaskControl",
    "alt": "kCGEventFlagMaskAlternate",
    "option": "kCGEventFlagMaskAlternate",
}


def do_click(pid, x, y, button, count):
    Quartz = _q()  # noqa: N806
    down, up, btn = (getattr(Quartz, name) for name in BUTTONS[button])
    for i in range(count):
        for kind in (down, up):
            ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), btn)
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, i + 1)
            Quartz.CGEventPostToPid(pid, ev)
        time.sleep(0.06)
    return f"posted {count}x {button} click at ({x},{y}) to pid {pid}"


def do_scroll(pid, x, y, amount):
    Quartz = _q()  # noqa: N806
    ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, amount)
    Quartz.CGEventSetLocation(ev, (x, y))
    Quartz.CGEventPostToPid(pid, ev)
    return f"posted scroll {amount} at ({x},{y}) to pid {pid}"


def do_move(pid, x, y):
    Quartz = _q()  # noqa: N806
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPostToPid(pid, ev)
    return f"posted move to ({x},{y}) to pid {pid}"


def do_key(pid, key, flags):
    Quartz = _q()  # noqa: N806
    code = KEYS.get(key, None)
    if code is None:
        code = int(key)
    flagmask = 0
    for f in (flags.split("+") if flags else []):
        flagmask |= getattr(Quartz, FLAGS[f])
    for is_down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, is_down)
        if flagmask:
            Quartz.CGEventSetFlags(ev, flagmask)
        Quartz.CGEventPostToPid(pid, ev)
        time.sleep(0.02)
    return f"posted key {key} (code {code}) flags={flagmask} to pid {pid}"


def cursor_position() -> tuple[int, int]:
    Quartz = _q()  # noqa: N806
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return int(loc.x), int(loc.y)


def run(args) -> int:
    if args.cmd == "cursor":
        x, y = cursor_position()
        print(json.dumps({"cursor": [x, y]}))
        return 0

    if not darwin.permissions()["accessibility"]:
        print(json.dumps({"error": "accessibility_not_granted", "hint": darwin.permission_hint("accessibility")}), file=sys.stderr)
        return 2

    if args.cmd == "windows":
        windows = darwin.all_windows(args.app)
        if args.pid:
            windows = [w for w in windows if w["pid"] == int(args.pid)]
        print(json.dumps({"windows": windows}, ensure_ascii=False))
        return 0

    win = None
    if args.window_id:
        win = darwin.window_info(args.window_id)
        if win is None:
            print(json.dumps({"ok": False, "reason": "target_changed", "detail": "window not found"}, ensure_ascii=False))
            return 5
        if args.expect and args.expect != darwin.target_sig(win):
            print(json.dumps(
                {"ok": False, "reason": "target_changed", "expected": args.expect, "actual": darwin.target_sig(win)},
                ensure_ascii=False,
            ))
            return 5
        pid = win["pid"]
        if args.x is not None and args.y is not None:
            args.x = win["bounds"][0] + args.x
            args.y = win["bounds"][1] + args.y
    else:
        pid = darwin.resolve_pid(args.app, args.pid)
        if pid is None:
            print(json.dumps({"ok": False, "reason": "app_not_found", "app": args.app}, ensure_ascii=False))
            return 2

    if args.cmd == "pid":
        print(json.dumps({"pid": pid}))
        return 0

    if args.cmd in ("click", "move", "scroll") and (args.x is None or args.y is None):
        print(json.dumps({"error": "--x/--y required for this command"}), file=sys.stderr)
        return 2
    if args.cmd == "key" and not args.key:
        print(json.dumps({"error": "--key required"}), file=sys.stderr)
        return 2

    sig = darwin.target_sig(win) if win else None
    if args.show and args.x is not None:
        darwin.show_overlay(args.x, args.y, args.key or args.cmd)

    result: dict[str, Any] = {
        "ok": True,
        "pid": pid,
        "target": sig,
        "global": [args.x, args.y] if args.x is not None else None,
        "action_sent": True,
    }
    if args.cmd == "click":
        result["detail"] = do_click(pid, args.x, args.y, args.button, args.count)
    elif args.cmd == "move":
        result["detail"] = do_move(pid, args.x, args.y)
    elif args.cmd == "scroll":
        result["detail"] = do_scroll(pid, args.x, args.y, args.amount)
    elif args.cmd == "key":
        result["detail"] = do_key(pid, args.key, args.flags)
    print(json.dumps(result, ensure_ascii=False))
    return 0
