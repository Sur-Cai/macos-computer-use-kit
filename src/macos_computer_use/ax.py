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

from . import darwin, gate, policy
from .results import EXIT_NOT_FOUND, EXIT_POLICY, EXIT_TIMEOUT, EXIT_USAGE, fail


_TIMEOUT_SET = False
# Roles an agent can act on. Used by snapshots (`--interactive`) and annotated
# screenshots, so a 3000-node tree becomes the 60 things worth clicking.
INTERACTIVE_ROLES = frozenset(
    {
        "AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton",
        "AXComboBox", "AXTextField", "AXTextArea", "AXSearchField", "AXSecureTextField",
        "AXLink", "AXMenuItem", "AXMenuBarItem", "AXTab", "AXSlider", "AXIncrementor",
        "AXDisclosureTriangle", "AXCell", "AXRow", "AXSwitch", "AXToggle", "AXColorWell",
        "AXDateField", "AXSegmentedControl", "AXDockItem",
    }
)


def _ax():
    global _TIMEOUT_SET
    AS, _NSWorkspace, _Quartz = darwin._pyobjc()  # noqa: N806
    if not _TIMEOUT_SET:
        # A hung app must not hang the agent: cap every AX round trip. Setting
        # the timeout on the system-wide element makes it the process default.
        _TIMEOUT_SET = True
        try:
            seconds = float(os.environ.get("MACOS_CU_AX_TIMEOUT", "3"))
            AS.AXUIElementSetMessagingTimeout(AS.AXUIElementCreateSystemWide(), seconds)
        except Exception:  # pragma: no cover - defensive
            pass
    return AS


def enable_enhanced_ax(app_el) -> bool:
    """Ask Chromium/Electron apps to build their full accessibility tree.

    Electron apps expose an almost empty tree until an assistive client sets
    ``AXManualAccessibility`` (Electron) or ``AXEnhancedUserInterface``
    (Chromium) on the application element. Harmless on native apps (the call
    just fails). Returns True when either attribute was accepted.
    """
    AS = _ax()  # noqa: N806
    ok = False
    for name in ("AXManualAccessibility", "AXEnhancedUserInterface"):
        try:
            if AS.AXUIElementSetAttributeValue(app_el, name, True) == 0:
                ok = True
        except Exception:  # pragma: no cover - defensive
            pass
    return ok


def element_ref(role: str, subrole: str, ident: str, title: str, desc: str, window: str) -> str:
    """Short, content-derived element reference (stable across re-reads).

    Path ids (``0.1.0.6``) break as soon as a sibling appears; a ref built from
    what the element *is* survives layout churn. Collisions are disambiguated by
    the caller with a ``~N`` suffix.
    """
    key = "\x1f".join((role, subrole, ident, title, desc, window))
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:8]


def _is_secure(role: str, subrole: str) -> bool:
    return policy.SECURE_ROLES.intersection({role, subrole}) != set()


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


MAX_NODES = 4000


def walk(el, depth, max_depth, out, role_filter=None, path="0", interactive=False, _ctx=None, menus=False):
    """Depth-first AX walk into ``out``.

    Each entry carries a path ``id`` (fast to resolve, fragile) and a content
    ``ref`` (stable across re-reads). Secure text fields never expose a value.
    The menu bar is skipped unless ``menus`` is set (closed menus hold hundreds
    of invisible items; ``macos-cu menu`` is the right tool for them), and
    ``interactive`` walks drop zero-size (invisible) elements.
    """
    AS = _ax()  # noqa: N806
    if _ctx is None:
        _ctx = {"window": "", "seen": {}, "geom": set()}
    if len(out) >= MAX_NODES or depth > max_depth:
        return
    role = attr(el, AS.kAXRoleAttribute) or ""
    if role == "AXMenuBar" and not menus:
        return
    subrole = attr(el, AS.kAXSubroleAttribute) or ""
    title = attr(el, AS.kAXTitleAttribute) or ""
    desc = attr(el, AS.kAXDescriptionAttribute) or ""
    ident = attr(el, "AXIdentifier") or ""
    value = attr(el, AS.kAXValueAttribute)
    if _is_secure(str(role), str(subrole)):
        value = policy.REDACTED if value else None
    elif isinstance(value, str):
        value = value.replace("\n", " ")[:60]
    elif isinstance(value, bool) or isinstance(value, (int, float)):
        value = str(value)
    else:
        value = None
    if role == "AXWindow":
        _ctx = {**_ctx, "window": str(title)}
    pos = point_of(el)
    size = size_of(el)
    children = attr(el, AS.kAXChildrenAttribute) or []
    matches = (not role_filter) or (role_filter.lower() in str(role).lower())
    if interactive and (role not in INTERACTIVE_ROLES or not size or size[0] < 1 or size[1] < 1):
        matches = False
    if matches and (title or desc or value or (size and size[0] > 4 and size[1] > 4)):
        # Some apps (Finder's desktop) expose the same control under several
        # parents; one entry per role + label + geometry is enough.
        geom = (str(role), str(title), str(desc), pos, size)
        if geom in _ctx["geom"]:
            matches = False
        else:
            _ctx["geom"].add(geom)
    if matches and (title or desc or value or (size and size[0] > 4 and size[1] > 4)):
        ref = element_ref(str(role), str(subrole), str(ident), str(title), str(desc), _ctx["window"])
        n = _ctx["seen"].get(ref, 0) + 1
        _ctx["seen"][ref] = n
        entry = {
            "id": path,
            "ref": ref if n == 1 else f"{ref}~{n}",
            "role": role,
            "title": title,
            "desc": desc,
            "value": value,
            "pos": pos,
            "size": size,
            "depth": depth,
            "children": len(children),
        }
        if subrole:
            entry["subrole"] = subrole
        if ident:
            entry["identifier"] = ident
        out.append(entry)
    for i, child in enumerate(children[:200]):
        walk(child, depth + 1, max_depth, out, role_filter, f"{path}.{i}", interactive, _ctx, menus)


def walk_app(root, depth, role_filter=None, interactive=False, enhance=True, menus=None):
    """Walk an app root; retry once with the Electron/Chromium tree enabled
    when the first pass comes back nearly empty. Menus are included only when
    asked for, or when the role filter is about menus."""
    if menus is None:
        menus = bool(role_filter and "menu" in role_filter.lower())
    out: list[dict[str, Any]] = []
    walk(root, 0, depth, out, role_filter, interactive=interactive, menus=menus)
    if enhance and len(out) < 8 and enable_enhanced_ax(root):
        time.sleep(0.35)
        out = []
        walk(root, 0, depth, out, role_filter, interactive=interactive, menus=menus)
    return out


def find_by_ref(root, ref, depth):
    """Entries whose ref equals ``ref``, whichever walk produced it.

    Refs come from snapshots (``--interactive``), plain finds and menu-bar
    finds, and the ``~N`` collision suffix depends on which elements that walk
    counted. Snapshots are the recommended source, so their walk goes first;
    the other variants are only tried on a miss.
    """
    depth = max(depth, 24)
    for interactive, menus in ((True, False), (False, False), (False, True), (True, True)):
        hits = [e for e in walk_app(root, depth, interactive=interactive, menus=menus) if e["ref"] == ref]
        if hits:
            return hits
    return []


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
        role = attr(focused, AS.kAXRoleAttribute) or ""
        subrole = attr(focused, AS.kAXSubroleAttribute) or ""
        f["focused_role"] = role
        value = str(attr(focused, AS.kAXValueAttribute) or "")
        # Password fields never leak into results, even as a fingerprint.
        f["focused_value"] = (policy.REDACTED if value else "") if _is_secure(str(role), str(subrole)) else value[:80]
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


def filter_title(found, title):
    if not title:
        return found
    needle = title.lower()
    return [
        e
        for e in found
        if needle in (e["title"] or "").lower()
        or needle in (e["desc"] or "").lower()
        or needle in (e["value"] or "").lower()
    ]


def locate(root, args):
    """Return (element, entry) for --ref, --id, or role/title filters.

    A ``--ref`` that no longer resolves returns ``(None, {"stale_ref": ...})``
    so the caller can say *re-observe* instead of acting on a guess.
    """
    AS = _ax()  # noqa: N806
    if getattr(args, "ref", None):
        hits = find_by_ref(root, args.ref, args.depth)
        if not hits:
            return None, {"stale_ref": args.ref}
        entry = hits[0]
        return element_at_path(root, entry["id"]), entry
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
    found = filter_title(walk_app(root, args.depth, args.role), args.title)
    if not found:
        return None, None
    entry = found[0]
    return element_at_path(root, entry["id"]), entry


def action_names(el) -> list[str]:
    AS = _ax()  # noqa: N806
    try:
        err, names = AS.AXUIElementCopyActionNames(el, None)
    except Exception:  # pragma: no cover - defensive
        return []
    return [str(n) for n in (names or [])] if err == 0 else []


def _element_summary(el, entry) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "ref": entry.get("ref"),
        "role": entry.get("role"),
        "title": entry.get("title"),
    }


def run_action(root, args) -> dict[str, Any]:
    """press / setvalue / action / focus on a located element, with read-back."""
    AS = _ax()  # noqa: N806
    el, entry = locate(root, args)
    if el is None:
        if entry and entry.get("stale_ref"):
            return fail(
                "stale_ref",
                retry="reobserve",
                ref=entry["stale_ref"],
                hint="the element this ref pointed at is gone or changed; take a fresh snapshot",
            )
        return fail("element_not_found", hint="re-read the tree (ax find / ax snapshot) and check role/title")

    coords = None
    pos = point_of(el)
    size = size_of(el)
    if pos and size:
        coords = [pos[0] + size[0] // 2, pos[1] + size[1] // 2]
    element = _element_summary(el, entry)
    pid = getattr(args, "_pid", None)

    if args.cmd == "setvalue":
        role = str(attr(el, AS.kAXRoleAttribute) or "")
        subrole = str(attr(el, AS.kAXSubroleAttribute) or "")
        if _is_secure(role, subrole):
            return fail("secure_field", retry="never", element=element,
                        hint="refusing to write into a password field; ask the user to do it")

    refusal = gate.check(pid, typing=args.cmd == "setvalue")
    if refusal:
        return refusal
    dry = gate.dry_run_result(f"ax_{args.cmd}", element=element, coords=coords)
    if dry:
        return dry

    before = app_fingerprint(root)

    if args.cmd in ("press", "action"):
        name = AS.kAXPressAction if args.cmd == "press" else (args.name or "")
        if args.cmd == "action":
            available = action_names(el)
            if name not in available:
                return fail("action_not_supported", retry="never", action=name, available=available, element=element)
        err = AS.AXUIElementPerformAction(el, name)
        time.sleep(0.4)
        after = app_fingerprint(root)
        changed = before != after
        result = {
            "ok": err == 0,
            "action": "ax_press" if args.cmd == "press" else f"ax_action:{name}",
            "err": int(err),
            "action_sent": True,
            "verified": bool(err == 0 and changed),
            "state_changed": changed,
            "before": before,
            "after": after,
            "coords": coords,
            "element": element,
        }
        if not result["verified"]:
            result["hint"] = (
                "The AX action did not change observable state; the element may be custom-drawn. "
                "Fall back to a coordinate click (macos-cu input click) after re-reading geometry."
            )
        gate.record(result["action"], pid, element=element)
        return result

    if args.cmd == "focus":
        err = AS.AXUIElementSetAttributeValue(el, AS.kAXFocusedAttribute, True)
        time.sleep(0.15)
        focused = bool(attr(el, AS.kAXFocusedAttribute))
        gate.record("ax_focus", pid, element=element)
        return {"ok": err == 0, "action": "ax_focus", "err": int(err), "action_sent": True,
                "verified": focused, "coords": coords, "element": element}

    err = AS.AXUIElementSetAttributeValue(el, AS.kAXValueAttribute, args.text)
    time.sleep(0.2)
    readback = attr(el, AS.kAXValueAttribute)
    result = {
        "ok": err == 0,
        "action": "ax_set_value",
        "err": int(err),
        "action_sent": True,
        "verified": bool(err == 0 and str(readback) == args.text),
        "readback": str(readback)[:80] if readback is not None else None,
        "coords": coords,
        "element": element,
    }
    if not result["verified"]:
        result["hint"] = (
            "AXValue is not settable here; use `macos-cu input type` or `macos-cu paste` instead."
        )
    gate.record("ax_set_value", pid, element=element, text=policy.redact_text(args.text))
    return result


def snapshot_cache_dir() -> str:
    base = os.environ.get("MACOS_CU_CACHE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "macos-computer-use"
    )
    path = os.path.join(base, "snapshots")
    # Snapshots hold whatever text was on screen: keep them private to the user.
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - defensive
        pass
    return path


SNAPSHOT_KEEP = 20


def prune_snapshots(path: str, keep: int | None = None) -> None:
    """Delete all but the newest ``keep`` cached snapshots (MACOS_CU_SNAPSHOT_KEEP)."""
    if keep is None:
        try:
            keep = int(os.environ.get("MACOS_CU_SNAPSHOT_KEEP", SNAPSHOT_KEEP))
        except ValueError:
            keep = SNAPSHOT_KEEP
    try:
        files = [os.path.join(path, f) for f in os.listdir(path) if f.endswith(".json")]
        files.sort(key=os.path.getmtime, reverse=True)
        for f in files[max(keep, 1):]:
            os.remove(f)
    except OSError:  # pragma: no cover - pruning must never break a snapshot
        pass


def app_root(args):
    """Resolve --pid/--app to an AX application element."""
    AS = _ax()  # noqa: N806
    if getattr(args, "pid", None):
        return AS.AXUIElementCreateApplication(int(args.pid)), int(args.pid)
    app = darwin.find_app(args.app)
    if app is None:
        return None, None
    return AS.AXUIElementCreateApplication(app.processIdentifier()), app


def diff_elements(before: list[dict[str, Any]], after: list[dict[str, Any]], limit: int = 50) -> dict[str, Any]:
    """Structural diff of two element lists keyed by content ref.

    Pure function: used by ``ax snapshot --diff`` and unit-tested directly.
    """
    def key(e):
        return e.get("ref") or e.get("id")

    b = {key(e): e for e in before}
    a = {key(e): e for e in after}
    added = [a[k] for k in a if k not in b]
    removed = [b[k] for k in b if k not in a]
    changed = []
    for k in a.keys() & b.keys():
        fields = [f for f in ("value", "title", "pos", "size") if a[k].get(f) != b[k].get(f)]
        if fields:
            changed.append({"ref": k, "role": a[k].get("role"), "fields": fields,
                            "before": {f: b[k].get(f) for f in fields}, "after": {f: a[k].get(f) for f in fields}})
    return {
        "no_change": not (added or removed or changed),
        "added": added[:limit],
        "removed": [{"ref": key(e), "role": e.get("role"), "title": e.get("title")} for e in removed[:limit]],
        "changed": changed[:limit],
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }


def element_at(x: float, y: float) -> dict[str, Any]:
    """Hit-test the AX element under a global screen point."""
    AS = _ax()  # noqa: N806
    err, el = AS.AXUIElementCopyElementAtPosition(AS.AXUIElementCreateSystemWide(), float(x), float(y), None)
    if err != 0 or el is None:
        return fail("element_not_found", retry="reobserve", point=[x, y])
    role = attr(el, AS.kAXRoleAttribute) or ""
    subrole = attr(el, AS.kAXSubroleAttribute) or ""
    value = attr(el, AS.kAXValueAttribute)
    if _is_secure(str(role), str(subrole)):
        value = policy.REDACTED if value else None
    try:
        err2, pid = AS.AXUIElementGetPid(el, None)
    except Exception:  # pragma: no cover - defensive
        pid = None
    pos, size = point_of(el), size_of(el)
    return {
        "ok": True,
        "point": [x, y],
        "role": role,
        "subrole": subrole or None,
        "title": attr(el, AS.kAXTitleAttribute) or "",
        "desc": attr(el, AS.kAXDescriptionAttribute) or "",
        "value": str(value)[:120] if value is not None else None,
        "pos": pos,
        "size": size,
        "actions": action_names(el),
        "app": darwin.app_info_for_pid(pid) if pid else None,
    }


def _print_err(obj: dict[str, Any], code: int) -> int:
    print(json.dumps(obj, ensure_ascii=False), file=sys.stderr)
    return code


def run(args) -> int:
    if args.cmd == "resolve":
        if not args.file or not (args.id or args.ref):
            return _print_err({"error": "resolve needs --file and --id or --ref"}, EXIT_USAGE)
        with open(args.file) as fh:
            data = json.load(fh)
        for e in data["elements"]:
            if (args.id and e["id"] == args.id) or (args.ref and e.get("ref") == args.ref):
                print(json.dumps(e, ensure_ascii=False))
                return 0
        return _print_err({"error": "id_not_found", "id": args.id or args.ref}, EXIT_NOT_FOUND)

    if not darwin.permissions()["accessibility"]:
        return _print_err({"error": "accessibility_not_granted", "hint": darwin.permission_hint("accessibility")}, EXIT_USAGE)

    if args.cmd == "at":
        if args.x is None or args.y is None:
            return _print_err({"error": "ax at needs --x and --y"}, EXIT_USAGE)
        result = element_at(args.x, args.y)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else EXIT_NOT_FOUND

    if args.cmd in ACTION_CMDS and not (args.pid or args.app):
        return _print_err({"error": f"{args.cmd} needs --app or --pid"}, EXIT_USAGE)
    if args.cmd == "setvalue" and args.text is None:
        return _print_err({"error": "setvalue needs --text"}, EXIT_USAGE)
    if args.cmd == "action" and not args.name:
        return _print_err({"error": "action needs --name (see `ax actions`)"}, EXIT_USAGE)

    root, app = app_root(args)
    if root is None:
        return _print_err({"error": "app_not_found", "app": args.app}, EXIT_USAGE)
    args._pid = int(app) if isinstance(app, int) else int(app.processIdentifier())

    if args.cmd in ACTION_CMDS:
        result = run_action(root, args)
        print(json.dumps(result, ensure_ascii=False))
        if result.get("ok"):
            return 0
        reason = result.get("reason", "")
        if reason in ("stale_ref", "element_not_found"):
            return EXIT_NOT_FOUND
        if reason in ("app_denied", "app_not_allowed", "sensitive_app", "secure_input_active",
                      "secure_field", "screen_locked"):
            return EXIT_POLICY
        return 0 if result.get("action_sent") else EXIT_USAGE

    if args.cmd == "actions":
        el, entry = locate(root, args)
        if el is None:
            print(json.dumps(fail("element_not_found"), ensure_ascii=False))
            return EXIT_NOT_FOUND
        print(json.dumps({"ok": True, "element": _element_summary(el, entry), "actions": action_names(el)},
                         ensure_ascii=False))
        return 0

    if args.cmd == "wait":
        return wait_for(root, args)

    out = filter_title(walk_app(root, args.depth, args.role, interactive=args.interactive), args.title)

    if args.cmd == "click-info" and args.index is not None:
        out = [out[args.index]] if 0 <= args.index < len(out) else []
    elif args.cmd in ("find", "tree", "click-info"):
        # Cap results for these modes; `snapshot` is bounded by --budget instead.
        out = out[: args.max]

    app_name = (
        app.localizedName()
        if hasattr(app, "localizedName")
        else darwin.app_info_for_pid(args._pid).get("name") or f"pid:{args.pid}"
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

    if args.cmd == "snapshot":
        return _snapshot(app_name, result, args)

    if args.json:
        print(json.dumps({"app": app_name, "count": len(result), "elements": result}, ensure_ascii=False))
        return 0

    print(f"app={app_name} elements={len(result)}")
    for e in result:
        t = (e["title"] or e["desc"] or e["value"] or "")[:50]
        loc = f"@screen{e['center_screen']}" if e.get("center_screen") else ""
        if e.get("center_shot"):
            loc += f" shot{e['center_shot']}"
        sz = f"{e['size'][0]}x{e['size'][1]}" if e["size"] else "-"
        print(f"[{e['idx']:>3}] {e['role']:<24} {sz:>10} {loc:<34} {t}  #{e['ref']}")
    return 0


ACTION_CMDS = ("press", "setvalue", "action", "focus")


def _snapshot(app_name: str, result: list[dict[str, Any]], args) -> int:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(app_name))
    cache = args.file_out or args.file or os.path.join(snapshot_cache_dir(), f"{safe}-{int(time.time() * 1000)}.json")
    diff = None
    if args.diff:
        try:
            with open(args.diff) as fh:
                diff = diff_elements(json.load(fh).get("elements", []), result)
        except (OSError, ValueError) as exc:
            diff = {"error": f"cannot read --diff snapshot: {exc}"}
    fd = os.open(cache, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"app": app_name, "ts": time.time(), "elements": result}, fh, ensure_ascii=False)
    if not (args.file_out or args.file):
        prune_snapshots(os.path.dirname(cache))

    if args.json:
        payload: dict[str, Any] = {"app": app_name, "snapshot": cache, "count": len(result)}
        if diff is not None:
            payload["diff"] = diff
        else:
            payload["elements"] = result
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if diff is not None and "error" not in diff:
        print(f"# snapshot: {cache} | diff vs {args.diff}: "
              f"+{diff['counts']['added']} -{diff['counts']['removed']} ~{diff['counts']['changed']}")
        if diff["no_change"]:
            print("# no_change")
        for e in diff["added"]:
            print(f"+ #{e['ref']} {e['role']} {(e['title'] or e['desc'] or e['value'] or '')[:60]}")
        for e in diff["removed"]:
            print(f"- #{e['ref']} {e['role']} {(e.get('title') or '')[:60]}")
        for c in diff["changed"]:
            print(f"~ #{c['ref']} {c['role']} {c['fields']} {json.dumps(c['after'], ensure_ascii=False)[:80]}")
        return 0

    lines = []
    used = 0
    omitted = 0
    for e in result:
        t = (e["title"] or e["desc"] or e["value"] or "")[:60]
        loc = f"@screen{e['center_screen']}" if e.get("center_screen") else ""
        sz = f"{e['size'][0]}x{e['size'][1]}" if e["size"] else "-"
        line = f"#{e['ref']:<10} {e['role']:<20} {sz:>9} {loc:<20} {t}"
        if used + len(line) + 1 > args.budget:
            omitted += 1
            continue
        lines.append(line)
        used += len(line) + 1
    print(f"# snapshot: {cache} | elements={len(result)} shown={len(lines)} omitted={omitted} (budget={args.budget})")
    if omitted:
        print("# narrow with --interactive / --role / --title, or raise --budget")
    print("\n".join(lines))
    return 0


def wait_for(root, args) -> int:
    """Poll until an element matching role/title (or --ref) appears, disappears,
    or (with --value) holds a value. Exit 7 on timeout."""
    deadline = time.time() + args.timeout
    polls = 0
    while True:
        polls += 1
        if args.ref:
            found = find_by_ref(root, args.ref, args.depth)
        else:
            found = filter_title(walk_app(root, args.depth, args.role), args.title)
        if args.value is not None:
            found = [e for e in found if args.value.lower() in str(e.get("value") or "").lower()]
        satisfied = (not found) if args.gone else bool(found)
        if satisfied:
            print(json.dumps({"ok": True, "condition": "gone" if args.gone else "present", "polls": polls,
                              "element": found[0] if found else None}, ensure_ascii=False))
            return 0
        if time.time() >= deadline:
            print(json.dumps(fail("timeout", retry="reobserve", polls=polls, timeout=args.timeout,
                                  condition="gone" if args.gone else "present"), ensure_ascii=False))
            return EXIT_TIMEOUT
        time.sleep(args.interval)
