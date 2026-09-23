"""Process- and window-scoped input for macOS.

Delivers mouse/keyboard events straight to a target process's event queue with
``CGEventPostToPid``, so the system cursor never moves and the user's physical
mouse is untouched. Window-scoped actions take window-relative coordinates and
can validate a target signature before acting, which turns "the window moved
while I was aiming" into an explicit ``target_changed`` refusal instead of a
misclick.

Every mutating command goes through ``gate.check`` first (sensitive apps,
secure input, locked screen, system chords) and honours ``MACOS_CU_DRY_RUN``.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from . import darwin, gate, keys
from .results import EXIT_POLICY, EXIT_TARGET_CHANGED, EXIT_USAGE, fail


def _q():
    _AS, _NSWorkspace, Quartz = darwin._pyobjc()  # noqa: N806
    return Quartz


BUTTONS = {
    "left": ("kCGEventLeftMouseDown", "kCGEventLeftMouseUp", "kCGMouseButtonLeft", "kCGEventLeftMouseDragged"),
    "right": ("kCGEventRightMouseDown", "kCGEventRightMouseUp", "kCGMouseButtonRight", "kCGEventRightMouseDragged"),
    "middle": ("kCGEventOtherMouseDown", "kCGEventOtherMouseUp", "kCGMouseButtonCenter", "kCGEventOtherMouseDragged"),
}

# Kept for backwards compatibility with code that imported these tables.
KEYS = keys.KEYS
FLAGS = {alias: keys.FLAG_CONSTANTS[canon] for alias, canon in keys.MODIFIERS.items()}


def _post(pid: int | None, ev, mode: str = "pid") -> None:
    Quartz = _q()  # noqa: N806
    if mode == "pid" and pid is not None:
        Quartz.CGEventPostToPid(pid, ev)
    else:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _flagmask(mods: list[str]) -> int:
    Quartz = _q()  # noqa: N806
    mask = 0
    for m in mods:
        mask |= getattr(Quartz, keys.FLAG_CONSTANTS[m])
    return mask


def do_click(pid, x, y, button, count, mode="pid", mods: list[str] | None = None):
    Quartz = _q()  # noqa: N806
    down, up, btn, _drag = (getattr(Quartz, name) for name in BUTTONS[button])
    mask = _flagmask(mods or [])
    # A double/triple click is ONE gesture whose events carry click states
    # 1, 2, 3 with no pause between them — that is what AppKit counts.
    for i in range(count):
        for kind in (down, up):
            ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), btn)
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, i + 1)
            if mask:
                Quartz.CGEventSetFlags(ev, mask)
            _post(pid, ev, mode)
        time.sleep(0.01 if count > 1 else 0.02)
    return f"posted {count}x {button} click at ({x},{y}) to pid {pid}"


def do_scroll(pid, x, y, amount, dx=0, unit="line", mode="pid"):
    Quartz = _q()  # noqa: N806
    kind = Quartz.kCGScrollEventUnitPixel if unit == "pixel" else Quartz.kCGScrollEventUnitLine
    # Quartz: positive wheel values scroll up/left. Our CLI: positive = down/right.
    ev = Quartz.CGEventCreateScrollWheelEvent(None, kind, 2, -int(amount), -int(dx))
    Quartz.CGEventSetLocation(ev, (x, y))
    _post(pid, ev, mode)
    return f"posted scroll dy={amount} dx={dx} ({unit}) at ({x},{y}) to pid {pid}"


def do_move(pid, x, y, mode="pid"):
    Quartz = _q()  # noqa: N806
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft)
    _post(pid, ev, mode)
    return f"posted move to ({x},{y}) to pid {pid}"


def do_drag(pid, x, y, to_x, to_y, button="left", steps=12, mode="pid", hold=0.08):
    Quartz = _q()  # noqa: N806
    down, up, btn, dragged = (getattr(Quartz, name) for name in BUTTONS[button])
    _post(pid, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), btn), mode)
    _post(pid, Quartz.CGEventCreateMouseEvent(None, down, (x, y), btn), mode)
    time.sleep(hold)
    steps = max(1, int(steps))
    for i in range(1, steps + 1):
        px = x + (to_x - x) * i / steps
        py = y + (to_y - y) * i / steps
        _post(pid, Quartz.CGEventCreateMouseEvent(None, dragged, (px, py), btn), mode)
        time.sleep(0.012)
    time.sleep(hold)
    _post(pid, Quartz.CGEventCreateMouseEvent(None, up, (to_x, to_y), btn), mode)
    return f"posted {button} drag ({x},{y}) -> ({to_x},{to_y}) in {steps} steps to pid {pid}"


def do_key(pid, key, flags, repeat=1, mode="pid"):
    Quartz = _q()  # noqa: N806
    code, mods, _name = keys.parse_chord(key, flags)
    mask = _flagmask(mods)
    for _ in range(max(1, int(repeat))):
        for is_down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, code, is_down)
            if mask:
                Quartz.CGEventSetFlags(ev, mask)
            _post(pid, ev, mode)
            time.sleep(0.02)
    return f"posted key {'+'.join([*mods, key.split('+')[-1]])} (code {code}) x{repeat} to pid {pid}"


def do_type(pid, text, mode="pid", chunk=16, delay=0.012):
    """Type Unicode text with keyboard events that carry the characters.

    ``CGEventKeyboardSetUnicodeString`` bypasses the keyboard layout and the
    input method, so CJK, emoji and accented text arrive intact — no clipboard
    involved. Newlines are sent as Return.
    """
    Quartz = _q()  # noqa: N806
    sent = 0
    for line_no, line in enumerate(text.split("\n")):
        if line_no:
            do_key(pid, "return", "", mode=mode)
        for i in range(0, len(line), chunk):
            piece = line[i : i + chunk]
            for is_down in (True, False):
                ev = Quartz.CGEventCreateKeyboardEvent(None, 0, is_down)
                Quartz.CGEventKeyboardSetUnicodeString(ev, len(piece.encode("utf-16-le")) // 2, piece)
                _post(pid, ev, mode)
            sent += len(piece)
            time.sleep(delay)
    return f"typed {len(text)} chars to pid {pid}"


def cursor_position() -> tuple[int, int]:
    Quartz = _q()  # noqa: N806
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return int(loc.x), int(loc.y)


def seconds_since_user_input() -> float | None:
    """Seconds since the last *physical* input, to avoid fighting the user."""
    try:
        Quartz = _q()  # noqa: N806
        return float(
            Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType
            )
        )
    except Exception:  # pragma: no cover - defensive
        return None


POINTER_CMDS = ("click", "move", "scroll", "drag", "hover")


def run(args) -> int:
    if args.cmd == "cursor":
        x, y = cursor_position()
        print(json.dumps({"cursor": [x, y], "idle_seconds": seconds_since_user_input()}))
        return 0

    if not darwin.permissions()["accessibility"]:
        print(json.dumps({"error": "accessibility_not_granted", "hint": darwin.permission_hint("accessibility")}), file=sys.stderr)
        return EXIT_USAGE

    if args.cmd == "windows":
        windows = darwin.all_windows(args.app)
        if args.pid:
            windows = [w for w in windows if w["pid"] == int(args.pid)]
        for w in windows:
            w["signature"] = darwin.target_sig(w)
        print(json.dumps({"windows": windows}, ensure_ascii=False))
        return 0

    win = None
    if args.window_id:
        win = darwin.window_info(args.window_id)
        if win is None:
            print(json.dumps(fail("target_changed", detail="window not found"), ensure_ascii=False))
            return EXIT_TARGET_CHANGED
        if args.expect and args.expect != darwin.target_sig(win):
            print(json.dumps(
                fail("target_changed", expected=args.expect, actual=darwin.target_sig(win)),
                ensure_ascii=False,
            ))
            return EXIT_TARGET_CHANGED
        pid = win["pid"]
        ox, oy = win["bounds"][0], win["bounds"][1]
        if args.x is not None and args.y is not None:
            args.x, args.y = ox + args.x, oy + args.y
        if getattr(args, "to_x", None) is not None and getattr(args, "to_y", None) is not None:
            args.to_x, args.to_y = ox + args.to_x, oy + args.to_y
    else:
        pid = darwin.resolve_pid(args.app, args.pid)
        if pid is None:
            print(json.dumps(fail("app_not_found", retry="never", app=args.app), ensure_ascii=False))
            return EXIT_USAGE

    if args.cmd == "pid":
        print(json.dumps({"pid": pid, **darwin.app_info_for_pid(pid)}, ensure_ascii=False))
        return 0

    if args.cmd in POINTER_CMDS and (args.x is None or args.y is None):
        print(json.dumps({"error": "--x/--y required for this command"}), file=sys.stderr)
        return EXIT_USAGE
    if args.cmd == "drag" and (args.to_x is None or args.to_y is None):
        print(json.dumps({"error": "--to-x/--to-y required for drag"}), file=sys.stderr)
        return EXIT_USAGE
    if args.cmd == "key" and not args.key:
        print(json.dumps({"error": "--key required"}), file=sys.stderr)
        return EXIT_USAGE
    if args.cmd == "type" and args.text is None:
        print(json.dumps({"error": "--text required"}), file=sys.stderr)
        return EXIT_USAGE

    system_chord = False
    if args.cmd == "click" and args.flags:
        try:
            keys.parse_modifiers(args.flags)
        except keys.KeyError_ as exc:
            print(json.dumps(fail("bad_key", retry="never", detail=str(exc)), ensure_ascii=False))
            return EXIT_USAGE
    if args.cmd == "key":
        try:
            _code, mods, name = keys.parse_chord(args.key, args.flags)
        except keys.KeyError_ as exc:
            print(json.dumps(fail("bad_key", retry="never", detail=str(exc)), ensure_ascii=False))
            return EXIT_USAGE
        system_chord = keys.is_system_chord(mods, name)

    refusal = gate.check(pid, typing=args.cmd in ("type", "key"), system_chord=system_chord)
    if refusal:
        print(json.dumps(refusal, ensure_ascii=False))
        return EXIT_POLICY

    sig = darwin.target_sig(win) if win else None
    point = [args.x, args.y] if args.x is not None else None
    dry = gate.dry_run_result(f"input_{args.cmd}", pid=pid, target=sig, **{"global": point})
    if dry:
        print(json.dumps(dry, ensure_ascii=False))
        return 0

    if args.show and args.x is not None:
        darwin.show_overlay(args.x, args.y, args.key or args.cmd)

    mode = getattr(args, "mode", "pid") or "pid"
    result: dict[str, Any] = {
        "ok": True,
        "pid": pid,
        "target": sig,
        "global": point,
        "action_sent": True,
    }
    if args.cmd == "click":
        mods = keys.parse_modifiers(args.flags)
        result["detail"] = do_click(pid, args.x, args.y, args.button, args.count, mode, mods)
    elif args.cmd in ("move", "hover"):
        result["detail"] = do_move(pid, args.x, args.y, mode)
    elif args.cmd == "scroll":
        result["detail"] = do_scroll(pid, args.x, args.y, args.amount, args.dx, args.unit, mode)
    elif args.cmd == "drag":
        result["detail"] = do_drag(pid, args.x, args.y, args.to_x, args.to_y, args.button, args.steps, mode)
        result["to"] = [args.to_x, args.to_y]
    elif args.cmd == "key":
        result["detail"] = do_key(pid, args.key, args.flags, args.repeat, mode)
    elif args.cmd == "type":
        result["detail"] = do_type(pid, args.text, mode)
    gate.record(
        f"input_{args.cmd}",
        pid,
        point=point,
        key=args.key if args.cmd == "key" else None,
        text=gate.policy.redact_text(args.text) if args.cmd == "type" else None,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0
