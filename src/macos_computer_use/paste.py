"""Clipboard-safe paste with takeover detection and clipboard restore.

Absorbed from ZCode's ``providedPaste`` pipeline (begin -> markDispatched ->
awaitRead -> finish) and its error taxonomy:

- ``pasteboard_write_failed``           nothing was sent
- ``pasteboard_changed_during_paste``   someone else took over the clipboard;
                                        verify the app did not paste the user's content
- ``pasteboard_read_timed_out``         the app never consumed the paste

The user's clipboard is saved before writing and restored afterwards, so an
agent pasting Chinese/CJK text never destroys what the user had copied.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import darwin, gate, policy
from .results import EXIT_POLICY


def _pb():
    _AS, _NSWorkspace, Quartz = darwin._pyobjc()  # noqa: N806
    from AppKit import NSPasteboard

    try:
        from AppKit import NSPasteboardTypeString as string_type
    except ImportError:  # pragma: no cover - legacy pyobjc
        from AppKit import NSStringPboardType as string_type
    return Quartz, NSPasteboard.generalPasteboard(), string_type


def read_text() -> str:
    _Quartz, board, string_type = _pb()  # noqa: N806
    return board.stringForType_(string_type) or ""


def write_text(text: str) -> bool:
    _Quartz, board, string_type = _pb()  # noqa: N806
    board.clearContents()
    return bool(board.setString_forType_(text, string_type))


def post_paste(pid: int | None, mode: str) -> None:
    Quartz, _board, _string_type = _pb()  # noqa: N806
    for is_down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, 9, is_down)  # 9 = V
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        if mode == "pid" and pid is not None:
            Quartz.CGEventPostToPid(pid, ev)
        else:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.02)


def run(args: argparse.Namespace) -> int:
    Quartz, board, _string_type = _pb()  # noqa: N806
    result = {"steps": []}

    pid = args.pid
    if pid is None and args.app:
        pid = darwin.resolve_pid(args.app)
    refusal = gate.check(pid, typing=True)
    if refusal:
        print(json.dumps(refusal, ensure_ascii=False))
        return EXIT_POLICY
    dry = gate.dry_run_result("paste", pid=pid, text=policy.redact_text(args.text), mode=args.mode)
    if dry:
        print(json.dumps(dry, ensure_ascii=False))
        return 0

    previous = read_text()
    before_count = board.changeCount()
    result["previous_len"] = len(previous)
    result["steps"].append("begin")

    if not write_text(args.text):
        result.update(ok=False, reason="pasteboard_write_failed", action_sent=False)
        print(json.dumps(result, ensure_ascii=False))
        return 3
    after_count = board.changeCount()
    result["steps"].append("written")

    if args.mode == "pid" and pid is None:
        result.update(ok=False, reason="target_app_not_found", action_sent=False)
        print(json.dumps(result, ensure_ascii=False))
        return 4
    post_paste(pid, args.mode)
    result["steps"].append(f"dispatched({args.mode})")

    time.sleep(args.wait)
    taken_over = board.changeCount() != after_count
    result["clipboard_taken_over"] = taken_over
    result["action_sent"] = True

    if taken_over:
        result.update(
            ok=False,
            reason="pasteboard_changed_during_paste",
            hint="someone else wrote the clipboard during the paste; check the app to make sure "
            "the user's content was not pasted instead",
            restored=False,
        )
    elif args.keep:
        result.update(ok=True, restored=False)
    else:
        if previous:
            write_text(previous)
            result["restored"] = True
        else:
            board.clearContents()
            result["restored"] = False
        result.update(ok=True)

    result["steps"].append("finished")
    gate.record("paste", pid, text=policy.redact_text(args.text), ok=result.get("ok"))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2
