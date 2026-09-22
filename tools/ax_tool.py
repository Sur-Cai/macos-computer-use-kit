#!/usr/bin/env python3
"""AX (Accessibility) helper for fast computer-use targeting.

Inspired by Codex's cua_repl: instead of screenshot -> vision -> estimate
coordinates, read the macOS accessibility tree and get exact element geometry.

Usage:
  ax_tool.py tree  [--app NAME] [--depth N] [--max N] [--role ROLE] [--json]
  ax_tool.py find  [--app NAME] --role ROLE [--title SUBSTR] [--json]
  ax_tool.py click-info [--app NAME] [--role ROLE] [--title SUBSTR] [--index N]

Coordinates are printed both in screen points (what AX reports) and in
"shot" space (what the computer-use MCP click tool expects), using
--shot-scale (default 0.9333 = 1372/1470 for this display).
"""

import argparse
import json
import sys
import time

import ApplicationServices as AS
from AppKit import NSWorkspace

DEFAULT_SHOT_SCALE = 0.9333


def find_app(name):
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    if not name:
        return NSWorkspace.sharedWorkspace().frontmostApplication()
    low = name.lower()
    for app in apps:
        localized = (app.localizedName() or "").lower()
        bundle = (app.bundleIdentifier() or "").lower()
        if low in (localized, bundle):
            return app
    for app in apps:
        localized = (app.localizedName() or "").lower()
        bundle = (app.bundleIdentifier() or "").lower()
        if low in localized or low in bundle:
            return app
    return None


def attr(el, name):
    err, value = AS.AXUIElementCopyAttributeValue(el, name, None)
    if err != 0:
        return None
    return value


def point_of(el):
    value = attr(el, AS.kAXPositionAttribute)
    if value is None:
        return None
    ok, pt = AS.AXValueGetValue(value, AS.kAXValueCGPointType, None)
    if not ok:
        return None
    return (int(pt.x), int(pt.y))


def size_of(el):
    value = attr(el, AS.kAXSizeAttribute)
    if value is None:
        return None
    ok, sz = AS.AXValueGetValue(value, AS.kAXValueCGSizeType, None)
    if not ok:
        return None
    return (int(sz.width), int(sz.height))


def walk(el, depth, max_depth, out, role_filter=None, seen=None, path="0"):
    if len(out) >= 4000 or depth > max_depth:
        return
    role = attr(el, AS.kAXRoleAttribute) or ""
    if role_filter and role_filter not in role:
        # still descend, children may match
        pass
    title = attr(el, AS.kAXTitleAttribute) or ""
    desc = attr(el, AS.kAXDescriptionAttribute) or ""
    value = attr(el, AS.kAXValueAttribute)
    if isinstance(value, str):
        value = value.replace("\n", " ")[:60]
    else:
        value = None
    pos = point_of(el)
    size = size_of(el)
    children = attr(el, AS.kAXChildrenAttribute) or []
    matches = (not role_filter) or (role_filter.lower() in role.lower())
    if matches and (title or desc or value or (size and size[0] > 4 and size[1] > 4)):
        out.append(
            {
                "id": path,
                "role": role,
                "title": title,
                "desc": desc,
                "value": value,
                "pos": pos,
                "size": size,
                "depth": depth,
                "children": len(children),
            }
        )
    for i, child in enumerate(children[:200]):
        walk(child, depth + 1, max_depth, out, role_filter, seen, f"{path}.{i}")


def element_at_path(el, path):
    """Resolve a snapshot-style path id (e.g. '0.1.0.6.0.0.0.0.5.8') to a live AXUIElement."""
    parts = str(path).split(".")
    if not parts or parts[0] != "0":
        return None
    cur = el
    for p in parts[1:]:
        children = attr(cur, AS.kAXChildrenAttribute) or []
        try:
            i = int(p)
        except ValueError:
            return None
        if i >= len(children):
            return None
        cur = children[i]
    return cur


def text_signature(root, limit=80):
    """Hash of the visible text in the window: catches pane/content changes."""
    import hashlib

    texts = []

    def collect(el, depth=0):
        if depth > 12 or len(texts) >= limit:
            return
        role = attr(el, AS.kAXRoleAttribute)
        if role in ("AXStaticText", "AXButton", "AXTextField", "AXTextArea"):
            v = attr(el, AS.kAXValueAttribute) or attr(el, AS.kAXTitleAttribute)
            if v:
                texts.append(str(v)[:40])
        for c in (attr(el, AS.kAXChildrenAttribute) or [])[:80]:
            collect(c, depth + 1)

    collect(root)
    return hashlib.md5("\n".join(texts).encode()).hexdigest()[:12], len(texts)


def app_fingerprint(root):
    """Small observable state used to verify that an AX action had an effect."""
    f = {}
    focused = attr(root, AS.kAXFocusedUIElementAttribute)
    if focused is not None:
        f["focused_role"] = attr(focused, AS.kAXRoleAttribute)
        f["focused_value"] = str(attr(focused, AS.kAXValueAttribute) or "")[:80]
    windows = attr(root, AS.kAXWindowsAttribute) or []
    if windows:
        w = windows[0]
        f["window_title"] = attr(w, AS.kAXTitleAttribute)
        kids = attr(w, AS.kAXChildrenAttribute) or []
        if kids:
            k = kids[0]
            f["pane_role"] = attr(k, AS.kAXRoleAttribute)
            f["pane_children"] = len(attr(k, AS.kAXChildrenAttribute) or [])
        sig, n = text_signature(w)
        f["text_sig"] = sig
        f["text_count"] = n
    return f


def locate(root, args):
    """Return (element, entry) for --id or role/title filters."""
    if args.id:
        el = element_at_path(root, args.id)
        if el is None:
            return None, None
        entry = {
            "id": args.id,
            "role": attr(el, AS.kAXRoleAttribute),
            "title": attr(el, AS.kAXTitleAttribute),
            "value": attr(el, AS.kAXValueAttribute),
        }
        return el, entry
    found = []
    walk(root, 0, args.depth, found, args.role)
    if args.title:
        needle = args.title.lower()
        found = [
            e
            for e in found
            if needle in (e["title"] or "").lower()
            or needle in (e["desc"] or "").lower()
            or needle in (e["value"] or "").lower()
        ]
    if not found:
        return None, None
    entry = found[0]
    return element_at_path(root, entry["id"]), entry


def run_action(root, args):
    el, entry = locate(root, args)
    if el is None:
        return {"ok": False, "reason": "element_not_found"}
    coords = None
    pos = point_of(el)
    size = size_of(el)
    if pos and size:
        coords = [pos[0] + size[0] // 2, pos[1] + size[1] // 2]

    before = app_fingerprint(root)
    if args.cmd == "press":
        err = AS.AXUIElementPerformAction(el, AS.kAXPressAction)
        time.sleep(0.4)
        after = app_fingerprint(root)
        changed = before != after
        verified = err == 0 and changed
        result = {
            "ok": True,
            "action": "ax_press",
            "err": int(err),
            "verified": verified,
            "state_changed": changed,
            "before": before,
            "after": after,
            "coords": coords,
            "element": {"id": entry.get("id"), "role": entry.get("role"), "title": entry.get("title")},
        }
        if not verified:
            result["hint"] = (
                "AXPress did not change observable state; fall back to a screenshot-coordinate click "
                "(computer-use left_click / assist.py click)"
            )
        return result

    # setvalue
    err = AS.AXUIElementSetAttributeValue(el, AS.kAXValueAttribute, args.text)
    time.sleep(0.2)
    readback = attr(el, AS.kAXValueAttribute)
    verified = err == 0 and str(readback) == args.text
    result = {
        "ok": True,
        "action": "ax_set_value",
        "err": int(err),
        "verified": verified,
        "readback": str(readback)[:80] if readback is not None else None,
        "coords": coords,
        "element": {"id": entry.get("id"), "role": entry.get("role"), "title": entry.get("title")},
    }
    if not verified:
        result["hint"] = (
            "AXValue is not settable here; use smart_paste.py (clipboard paste + verify) instead"
        )
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tree", "find", "click-info", "snapshot", "resolve", "press", "setvalue"])
    ap.add_argument("--app", default=None)
    ap.add_argument("--depth", type=int, default=16)
    ap.add_argument("--max", type=int, default=120)
    ap.add_argument("--role", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--index", type=int, default=None)
    ap.add_argument("--shot-scale", type=float, default=DEFAULT_SHOT_SCALE)
    ap.add_argument("--budget", type=int, default=4000, help="max characters of snapshot text")
    ap.add_argument("--file", default=None, help="snapshot cache file (for resolve)")
    ap.add_argument("--id", default=None, help="element id inside a snapshot (for resolve)")
    ap.add_argument("--text", default=None, help="text to set (for setvalue)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.cmd == "resolve":
        if not args.file or not args.id:
            print("resolve needs --file and --id", file=sys.stderr)
            return 2
        data = json.load(open(args.file))
        for e in data["elements"]:
            if e["id"] == args.id:
                print(json.dumps(e, ensure_ascii=False))
                return 0
        print(f"id not found: {args.id}", file=sys.stderr)
        return 3

    app = find_app(args.app)
    if app is None:
        print(f"app not found: {args.app}", file=sys.stderr)
        return 2

    root = AS.AXUIElementCreateApplication(app.processIdentifier())

    if args.cmd in ("press", "setvalue"):
        if args.cmd == "setvalue" and args.text is None:
            print("setvalue needs --text", file=sys.stderr)
            return 2
        print(json.dumps(run_action(root, args), ensure_ascii=False))
        return 0

    out = []
    walk(root, 0, args.depth, out, args.role)

    if args.title:
        needle = args.title.lower()
        out = [
            e
            for e in out
            if needle in (e["title"] or "").lower()
            or needle in (e["desc"] or "").lower()
            or needle in (e["value"] or "").lower()
        ]

    if args.cmd == "click-info" and args.index is not None:
        out = [out[args.index]] if 0 <= args.index < len(out) else []
    elif args.cmd == "find":
        pass
    else:
        out = out[: args.max]

    result = []
    for i, e in enumerate(out):
        entry = dict(e)
        entry["idx"] = i
        if e["pos"] and e["size"]:
            cx = e["pos"][0] + e["size"][0] // 2
            cy = e["pos"][1] + e["size"][1] // 2
            entry["center_screen"] = [cx, cy]
            entry["center_shot"] = [round(cx * args.shot_scale), round(cy * args.shot_scale)]
        result.append(entry)

    if args.json:
        print(json.dumps({"app": app.localizedName(), "count": len(result), "elements": result}, ensure_ascii=False))
        return 0

    if args.cmd == "snapshot":
        import os
        import time as _time

        lines = []
        used = 0
        omitted = 0
        for e in result:
            t = (e["title"] or e["desc"] or e["value"] or "")[:60]
            loc = f"@screen{e['center_screen']}" if e.get("center_screen") else ""
            sz = f"{e['size'][0]}x{e['size'][1]}" if e["size"] else "-"
            line = f"[{e['id']}] {e['role']:<22} {sz:>10} {loc:<22} {t}"
            if used + len(line) + 1 > args.budget:
                omitted += 1
                continue
            lines.append(line)
            used += len(line) + 1
        cache_dir = os.path.expanduser("~/.cache/ax-snapshots")
        os.makedirs(cache_dir, exist_ok=True)
        cache = os.path.join(cache_dir, f"{app.localizedName()}-{int(_time.time())}.json")
        json.dump({"app": app.localizedName(), "elements": result}, open(cache, "w"), ensure_ascii=False)
        print(f"# snapshot: {cache} | elements={len(result)} shown={len(lines)} omitted={omitted} (budget={args.budget})")
        print("\n".join(lines))
        return 0

    print(f"app={app.localizedName()} elements={len(result)} (shot-scale={args.shot_scale})")
    for e in result:
        t = (e["title"] or e["desc"] or e["value"] or "")[:50]
        loc = f"@screen{e['center_screen']} shot{e['center_shot']}" if e.get("center_screen") else ""
        sz = f"{e['size'][0]}x{e['size'][1]}" if e["size"] else "-"
        print(f"[{e['idx']:>3}] {e['role']:<24} {sz:>10} {loc:<34} {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
