#!/usr/bin/env python3
"""Assistive (process-targeted) input for macOS.

Delivers mouse/keyboard events straight to a target process's event queue with
CGEventPostToPid, so the system cursor never moves and the user's physical
mouse is untouched. This is the same mechanism Codex's Sky service uses
(SkyComputerUseService links CGEventPostToPid).

Usage:
  assist.py cursor
  assist.py pid --app "WeChat"
  assist.py click --app "WeChat" --x 813 --y 272 [--button left|right|middle] [--count 1]
  assist.py key   --app "WeChat" --key return [--flags cmd]
  assist.py move  --app "WeChat" --x 813 --y 272        # hover without cursor move

Coordinates are global display points (same space as AX positions / screenshot
screen coords). Use --pid to target a specific process id instead of --app.
"""

import argparse
import json
import sys
import time

import Quartz
from AppKit import NSWorkspace

BUTTONS = {
    "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft),
    "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight),
    "middle": (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter),
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
    "cmd": Quartz.kCGEventFlagMaskCommand,
    "command": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift,
    "ctrl": Quartz.kCGEventFlagMaskControl,
    "control": Quartz.kCGEventFlagMaskControl,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "option": Quartz.kCGEventFlagMaskAlternate,
}


def resolve_pid(args):
    if args.pid:
        return int(args.pid)
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    low = (args.app or "").lower()
    for app in apps:
        if low in ((app.localizedName() or "").lower(), (app.bundleIdentifier() or "").lower()):
            return int(app.processIdentifier())
    for app in apps:
        if low and low in ((app.localizedName() or "").lower() + (app.bundleIdentifier() or "").lower()):
            return int(app.processIdentifier())
    print(f"app not found: {args.app}", file=sys.stderr)
    return None


def window_info(window_id):
    """Resolve a CGWindowID to {pid, owner, title, bounds}."""
    for w in Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    ):
        if int(w.get("kCGWindowNumber", 0)) == int(window_id):
            b = w.get("kCGWindowBounds") or {}
            return {
                "id": int(window_id),
                "pid": int(w.get("kCGWindowOwnerPID", 0)),
                "owner": str(w.get("kCGWindowOwnerName") or ""),
                "title": str(w.get("kCGWindowName") or ""),
                "bounds": [
                    int(b.get("X", 0)),
                    int(b.get("Y", 0)),
                    int(b.get("Width", 0)),
                    int(b.get("Height", 0)),
                ],
            }
    return None


def target_sig(win):
    x, y, w, h = win["bounds"]
    return f'{win["pid"]}:{win["id"]}:{x}:{y}:{w}:{h}'


def list_windows(app_name=None):
    out = []
    for w in Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    ):
        owner = str(w.get("kCGWindowOwnerName") or "")
        if app_name and app_name.lower() not in owner.lower():
            continue
        b = w.get("kCGWindowBounds") or {}
        if int(b.get("Width", 0)) < 50:
            continue
        out.append(
            {
                "id": int(w.get("kCGWindowNumber", 0)),
                "pid": int(w.get("kCGWindowOwnerPID", 0)),
                "owner": owner,
                "title": str(w.get("kCGWindowName") or ""),
                "bounds": [int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0))],
                "layer": int(w.get("kCGWindowLayer", 0)),
            }
        )
    # main windows first: layer 0, then by area descending
    out.sort(key=lambda x: (x["layer"] != 0, -(x["bounds"][2] * x["bounds"][3])))
    return out


def show_overlay(x, y, label="", color="cyan", duration=1.2):
    import os
    import subprocess

    script = os.path.expanduser("~/.local/share/computer-use-ax/overlay.py")
    if not os.path.exists(script):
        return False
    subprocess.Popen(
        [sys.executable, script, "show", "--x", str(int(x)), "--y", str(int(y)), "--label", label,
         "--duration", str(duration), "--color", color],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return True


def do_click(pid, x, y, button, count):
    down, up, btn = BUTTONS[button]
    for i in range(count):
        for kind in (down, up):
            ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), btn)
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, i + 1)
            Quartz.CGEventPostToPid(pid, ev)
        time.sleep(0.06)
    return f"posted {count}x {button} click at ({x},{y}) to pid {pid}"


def do_scroll(pid, x, y, amount):
    ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, amount)
    Quartz.CGEventSetLocation(ev, (x, y))
    Quartz.CGEventPostToPid(pid, ev)
    return f"posted scroll {amount} at ({x},{y}) to pid {pid}"


def do_move(pid, x, y):
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPostToPid(pid, ev)
    return f"posted move to ({x},{y}) to pid {pid}"


def do_key(pid, key, flags):
    code = KEYS.get(key, None)
    if code is None:
        code = int(key)
    flagmask = 0
    for f in flags.split("+") if flags else []:
        flagmask |= FLAGS[f]
    for is_down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, is_down)
        if flagmask:
            Quartz.CGEventSetFlags(ev, flagmask)
        Quartz.CGEventPostToPid(pid, ev)
        time.sleep(0.02)
    return f"posted key {key} (code {code}) flags={flagmask} to pid {pid}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cursor", "pid", "windows", "click", "move", "key", "scroll"])
    ap.add_argument("--app")
    ap.add_argument("--pid")
    ap.add_argument("--window-id", type=int, help="target a specific window (CGWindowID)")
    ap.add_argument("--expect", help="expected target signature pid:wid:x:y:w:h; mismatch = target_changed")
    ap.add_argument("--show", action="store_true", help="draw a visual ring at the action point")
    ap.add_argument("--x", type=int)
    ap.add_argument("--y", type=int)
    ap.add_argument("--button", default="left")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--key")
    ap.add_argument("--flags", default="")
    ap.add_argument("--amount", type=int, default=-5, help="scroll lines: negative = up, positive = down")
    args = ap.parse_args()

    if args.cmd == "cursor":
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        print(f"cursor at ({int(loc.x)},{int(loc.y)})")
        return 0

    if args.cmd == "windows":
        print(json.dumps({"windows": list_windows(args.app)}, ensure_ascii=False))
        return 0

    win = None
    if args.window_id:
        win = window_info(args.window_id)
        if win is None:
            print(json.dumps({"ok": False, "reason": "target_changed", "detail": "window not found"}, ensure_ascii=False))
            return 5
        if args.expect and args.expect != target_sig(win):
            print(json.dumps({"ok": False, "reason": "target_changed", "expected": args.expect, "actual": target_sig(win)}, ensure_ascii=False))
            return 5
        pid = win["pid"]
        if args.x is not None and args.y is not None:
            args.x = win["bounds"][0] + args.x
            args.y = win["bounds"][1] + args.y
    else:
        pid = resolve_pid(args)
        if pid is None:
            print(json.dumps({"ok": False, "reason": "app_not_found", "app": args.app}, ensure_ascii=False))
            return 2

    if args.cmd == "pid":
        print(pid)
        return 0

    if args.cmd in ("click", "move", "scroll") and (args.x is None or args.y is None):
        print("--x/--y required", file=sys.stderr)
        return 2

    sig = target_sig(win) if win else None
    if args.show and args.x is not None:
        show_overlay(args.x, args.y, args.key or args.cmd)

    result = {"ok": True, "pid": pid, "target": sig, "global": [args.x, args.y] if args.x is not None else None}
    if args.cmd == "click":
        result["detail"] = do_click(pid, args.x, args.y, args.button, args.count)
    elif args.cmd == "move":
        result["detail"] = do_move(pid, args.x, args.y)
    elif args.cmd == "scroll":
        result["detail"] = do_scroll(pid, args.x, args.y, args.amount)
    elif args.cmd == "key":
        if not args.key:
            print("--key required", file=sys.stderr)
            return 2
        result["detail"] = do_key(pid, args.key, args.flags)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
