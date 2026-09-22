"""Accessibility (AX) tree reading, semantic targeting, and native AX actions.

Inspired by Codex's CUA repl: instead of screenshot -> vision -> estimate
coordinates, read the macOS accessibility tree and get exact element geometry.
`press`/`setvalue` additionally verify that the action changed observable state
before reporting success.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Any

from . import darwin


def _ax():
    AS, _NSWorkspace, _Quartz = darwin._pyobjc()  # noqa: N806
    return AS


def attr(el, name):
    AS = _ax()  # noqa: N806
    err, value = AS.AXUIElementCopyAttributeValue(el, name, None)
    if err != 0:
        return None
    return value


def point_of(el):
    AS = _ax()  # noqa: N806
    value = attr(el, AS.kAXPositionAttribute)
    if value is None:
        return None
    ok, pt = AS.AXValueGetValue(value, AS.kAXValueCGPointType, None)
    if not ok:
        return None
    return (int(pt.x), int(pt.y))


def size_of(el):
    AS = _ax()  # noqa: N806
    value = attr(el, AS.kAXSizeAttribute)
    if value is None:
        return None
    ok, sz = AS.AXValueGetValue(value, AS.kAXValueCGSizeType, None)
    if not ok:
        return None
    return (int(sz.width), int(sz.height))


def walk(el, depth, max_depth, out, role_filter=None, path="0"):
    AS = _ax()  # noqa: N806
    if len(out) >= 4000 or depth > max_depth:
        return
    role = attr(el, AS.kAXRoleAttribute) or ""
    title = attr(el, AS.kAXTitleAttribute) or ""
    desc = attr(el, AS.kAXDescriptionAttribute) or ""
    value = attr(el, AS.kAXValueAttribute)
    value = value.replace("\n", " ")[:60] if isinstance(value, str) else None
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
        walk(child, depth + 1, max_depth, out, role_filter, f"{path}.{i}")


def element_at_path(el, path):
    """Resolve a snapshot-style path id (e.g. '0.1.0.6.0') to a live AXUIElement."""
    AS = _ax()  # noqa: N806
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
    """Hash of the visible text in a window: catches pane/content changes."""
    AS = _ax()  # noqa: N806
    texts: list[str] = []

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


def app_fingerprint(root) -> dict[str, Any]:
    """Small observable state used to verify that an AX action had an effect."""
    AS = _ax()  # noqa: N806
    f: dict[str, Any] = {}
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
    AS = _ax()  # noqa: N806
    if getattr(args, "id", None):
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
    found: list[dict[str, Any]] = []
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


def run_action(root, args) -> dict[str, Any]:
    AS = _ax()  # noqa: N806
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
        result = {
            "ok": True,
            "action": "ax_press",
            "err": int(err),
            "verified": bool(err == 0 and changed),
            "state_changed": changed,
            "before": before,
            "after": after,
            "coords": coords,
            "element": {"id": entry.get("id"), "role": entry.get("role"), "title": entry.get("title")},
        }
        if not result["verified"]:
            result["hint"] = (
                "AXPress did not change observable state; the element may be custom-drawn. "
                "Fall back to a coordinate click (macos-cu input click) after re-reading geometry."
            )
        return result

    err = AS.AXUIElementSetAttributeValue(el, AS.kAXValueAttribute, args.text)
    time.sleep(0.2)
    readback = attr(el, AS.kAXValueAttribute)
    result = {
        "ok": True,
        "action": "ax_set_value",
        "err": int(err),
        "verified": bool(err == 0 and str(readback) == args.text),
        "readback": str(readback)[:80] if readback is not None else None,
        "coords": coords,
        "element": {"id": entry.get("id"), "role": entry.get("role"), "title": entry.get("title")},
    }
    if not result["verified"]:
        result["hint"] = (
            "AXValue is not settable here; use `macos-cu paste` (clipboard paste + verify) instead."
        )
    return result


def snapshot_cache_dir() -> str:
    base = os.environ.get("MACOS_CU_CACHE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "macos-computer-use"
    )
    path = os.path.join(base, "snapshots")
    os.makedirs(path, exist_ok=True)
    return path


def app_root(args):
    """Resolve --pid/--app to an AX application element."""
    AS = _ax()  # noqa: N806
    if getattr(args, "pid", None):
        return AS.AXUIElementCreateApplication(int(args.pid)), int(args.pid)
    app = darwin.find_app(args.app)
    if app is None:
        return None, None
    return AS.AXUIElementCreateApplication(app.processIdentifier()), app


def run(args) -> int:
    out: list[dict[str, Any]] = []

    if args.cmd == "resolve":
        if not args.file or not args.id:
            print(json.dumps({"error": "resolve needs --file and --id"}), file=sys.stderr)
            return 2
        with open(args.file) as fh:
            data = json.load(fh)
        for e in data["elements"]:
            if e["id"] == args.id:
                print(json.dumps(e, ensure_ascii=False))
                return 0
        print(json.dumps({"error": "id_not_found", "id": args.id}), file=sys.stderr)
        return 3

    if not darwin.permissions()["accessibility"]:
        print(json.dumps({"error": "accessibility_not_granted", "hint": darwin.permission_hint("accessibility")}), file=sys.stderr)
        return 2

    if args.cmd in ("press", "setvalue") and not (args.pid or args.app):
        print(json.dumps({"error": "press/setvalue need --app or --pid"}), file=sys.stderr)
        return 2
    if args.cmd == "setvalue" and args.text is None:
        print(json.dumps({"error": "setvalue needs --text"}), file=sys.stderr)
        return 2

    root, app = app_root(args)
    if root is None:
        print(json.dumps({"error": "app_not_found", "app": args.app}), file=sys.stderr)
        return 2

    if args.cmd in ("press", "setvalue"):
        print(json.dumps(run_action(root, args), ensure_ascii=False))
        return 0

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
    elif args.cmd in ("find", "tree", "click-info"):
        # Cap results for these modes; `snapshot` is bounded by --budget instead.
        out = out[: args.max]

    app_name = (
        app.localizedName()
        if hasattr(app, "localizedName")
        else darwin.find_app(args.app).localizedName() if args.app else f"pid:{args.pid}"
    )

    result = []
    for i, e in enumerate(out):
        entry = dict(e)
        entry["idx"] = i
        if e["pos"] and e["size"]:
            cx = e["pos"][0] + e["size"][0] // 2
            cy = e["pos"][1] + e["size"][1] // 2
            entry["center_screen"] = [cx, cy]
            # `shot` space only exists for harnesses whose screenshots are
            # scaled differently from screen points; opt in with --shot-scale.
            if args.shot_scale:
                entry["center_shot"] = [round(cx * args.shot_scale), round(cy * args.shot_scale)]
        result.append(entry)

    if args.json:
        print(json.dumps({"app": app_name, "count": len(result), "elements": result}, ensure_ascii=False))
        return 0

    if args.cmd == "snapshot":
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
        cache = os.path.join(snapshot_cache_dir(), f"{app_name}-{int(time.time())}.json")
        with open(cache, "w") as fh:
            json.dump({"app": app_name, "elements": result}, fh, ensure_ascii=False)
        print(f"# snapshot: {cache} | elements={len(result)} shown={len(lines)} omitted={omitted} (budget={args.budget})")
        print("\n".join(lines))
        return 0

    print(f"app={app_name} elements={len(result)}")
    for e in result:
        t = (e["title"] or e["desc"] or e["value"] or "")[:50]
        loc = f"@screen{e['center_screen']}" if e.get("center_screen") else ""
        if e.get("center_shot"):
            loc += f" shot{e['center_shot']}"
        sz = f"{e['size'][0]}x{e['size'][1]}" if e["size"] else "-"
        print(f"[{e['idx']:>3}] {e['role']:<24} {sz:>10} {loc:<34} {t}")
    return 0
