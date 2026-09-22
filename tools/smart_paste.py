#!/usr/bin/env python3
"""Clipboard-safe paste with takeover detection and clipboard restore.

Absorbed from ZCode's `providedPaste` pipeline (begin → markDispatched →
awaitRead → finish) and its error taxonomy:
  - pasteboard_write_failed        -> nothing was sent
  - pasteboard_changed_during_paste-> someone else took over the clipboard;
                                      verify the app did not paste the user's content
  - pasteboard_read_timed_out      -> the app never consumed the paste

Usage:
  smart_paste.py --app "WeChat" --text "..." [--mode pid|hid] [--wait 2.0] [--keep]

Exit codes: 0 = dispatched, 2 = clipboard taken over, 3 = write failed.
"""

import argparse
import json
import subprocess
import sys
import time

import Quartz
from AppKit import NSPasteboard, NSStringPboardType, NSWorkspace


def pasteboard():
    return NSPasteboard.generalPasteboard()


def read_text():
    return pasteboard().stringForType_(NSStringPboardType) or ""


def write_text(text):
    pb = pasteboard()
    pb.clearContents()
    return bool(pb.setString_forType_(text, NSStringPboardType))


def resolve_pid(name):
    low = (name or "").lower()
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    for app in apps:
        if low in ((app.localizedName() or "").lower(), (app.bundleIdentifier() or "").lower()):
            return int(app.processIdentifier())
    for app in apps:
        if low and low in ((app.localizedName() or "").lower() + (app.bundleIdentifier() or "").lower()):
            return int(app.processIdentifier())
    return None


def post_paste(pid, mode):
    for is_down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, 9, is_down)  # 9 = V
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        if mode == "pid":
            Quartz.CGEventPostToPid(pid, ev)
        else:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.02)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--text", required=True)
    ap.add_argument("--mode", choices=["pid", "hid"], default="pid")
    ap.add_argument("--wait", type=float, default=1.5)
    ap.add_argument("--keep", action="store_true", help="do not restore the previous clipboard")
    args = ap.parse_args()

    result = {"steps": []}

    # 1) begin: remember what the user had
    previous = read_text()
    pb = pasteboard()
    before_count = pb.changeCount()
    result["previous_len"] = len(previous)
    result["steps"].append("begin")

    # 2) write our text
    if not write_text(args.text):
        result.update(ok=False, reason="pasteboard_write_failed", action_sent=False)
        print(json.dumps(result, ensure_ascii=False))
        return 3
    after_count = pb.changeCount()
    result["steps"].append("written")

    # 3) dispatch the paste
    pid = args.pid
    if pid is None and args.app:
        pid = resolve_pid(args.app)
    if args.mode == "pid" and pid is None:
        result.update(ok=False, reason="target_app_not_found", action_sent=False)
        print(json.dumps(result, ensure_ascii=False))
        return 4
    post_paste(pid, args.mode)
    result["steps"].append(f"dispatched({args.mode})")

    # 4) await read: did someone else take over the pasteboard?
    time.sleep(args.wait)
    now_count = pb.changeCount()
    taken_over = now_count != after_count
    result["clipboard_taken_over"] = taken_over
    result["action_sent"] = True

    if taken_over:
        result.update(
            ok=False,
            reason="pasteboard_changed_during_paste",
            hint="someone else wrote the clipboard during the paste; check the app to make sure the user's content was not pasted instead",
            restored=False,
        )
    elif args.keep:
        result.update(ok=True, restored=False)
    else:
        # 5) finish: restore the user's clipboard
        if previous:
            write_text(previous)
            result["restored"] = True
        else:
            pb.clearContents()
            result["restored"] = False
        result.update(ok=True)

    result["steps"].append("finished")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
