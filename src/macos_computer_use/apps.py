"""App, window, and menu-bar control.

Semantic operations that agents otherwise fake with keystrokes: launch /
activate / hide / quit apps, open URLs and files, move / resize / minimize /
raise / close windows through AX, and walk the menu bar by path
(``"File > Export…"``) instead of guessing shortcuts.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

from . import ax, darwin, gate
from .results import EXIT_NOT_FOUND, EXIT_POLICY, EXIT_USAGE, fail


def _print(obj: dict[str, Any], code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return code


# ------------------------------------------------------------------ apps
def list_apps(include_background: bool = False) -> list[dict[str, Any]]:
    _AS, NSWorkspace, _Quartz = darwin._pyobjc()  # noqa: N806
    ws = NSWorkspace.sharedWorkspace()
    front = ws.frontmostApplication()
    front_pid = int(front.processIdentifier()) if front is not None else None
    out = []
    for app in ws.runningApplications():
        policy = int(app.activationPolicy())  # 0 regular, 1 accessory, 2 prohibited
        if policy == 2 or (policy == 1 and not include_background):
            continue
        pid = int(app.processIdentifier())
        out.append(
            {
                "name": str(app.localizedName() or ""),
                "bundle": str(app.bundleIdentifier() or ""),
                "pid": pid,
                "frontmost": pid == front_pid,
                "hidden": bool(app.isHidden()),
                "regular": policy == 0,
            }
        )
    out.sort(key=lambda a: (not a["frontmost"], a["name"].lower()))
    return out


def _looks_like_bundle(name: str) -> bool:
    return "." in name and " " not in name and not name.endswith(".app")


def launch(name: str, background: bool = False, wait: float = 8.0) -> dict[str, Any]:
    argv = ["open"]
    if background:
        argv.append("-g")
    argv += ["-b", name] if _looks_like_bundle(name) else ["-a", name]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("launch_failed", retry="never", app=name, stderr=proc.stderr.strip()[-200:])
    deadline = time.time() + wait
    while time.time() < deadline:
        app = darwin.find_app(name)
        if app is not None and app.isFinishedLaunching():
            return {"ok": True, "action": "launch", "action_sent": True, **darwin.app_info_for_pid(app.processIdentifier())}
        time.sleep(0.2)
    return fail("launch_timeout", action_sent=True, app=name, hint="the app may still be starting; check `app list`")


def activate(name: str | None, pid: int | None) -> dict[str, Any]:
    app = _running(name, pid)
    if app is None:
        return fail("app_not_found", retry="never", app=name or pid)
    # NSApplicationActivateIgnoringOtherApps = 1 << 1 (deprecated but still honoured)
    ok = bool(app.activateWithOptions_(1 << 1))
    time.sleep(0.25)
    _AS, NSWorkspace, _Quartz = darwin._pyobjc()  # noqa: N806
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    verified = front is not None and int(front.processIdentifier()) == int(app.processIdentifier())
    return {"ok": ok, "action": "activate", "action_sent": True, "verified": verified,
            **darwin.app_info_for_pid(app.processIdentifier())}


def _running(name: str | None, pid: int | None):
    if pid:
        from AppKit import NSRunningApplication

        return NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
    return darwin.find_app(name) if name else None


def open_target(target: str, app: str | None = None, background: bool = False) -> dict[str, Any]:
    """Open a URL or a file (optionally with a specific app) via LaunchServices."""
    argv = ["open"]
    if background:
        argv.append("-g")
    if app:
        argv += ["-b", app] if _looks_like_bundle(app) else ["-a", app]
    argv.append(target)
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("open_failed", retry="never", target=target, stderr=proc.stderr.strip()[-200:])
    return {"ok": True, "action": "open", "action_sent": True, "target": target, "app": app}


# --------------------------------------------------------------- windows
def ax_windows(root) -> list[dict[str, Any]]:
    AS = ax._ax()  # noqa: N806
    main = ax.attr(root, AS.kAXMainWindowAttribute)
    focused = ax.attr(root, AS.kAXFocusedWindowAttribute)
    out = []
    for i, w in enumerate(ax.attr(root, AS.kAXWindowsAttribute) or []):
        pos, size = ax.point_of(w), ax.size_of(w)
        out.append(
            {
                "index": i,
                "title": ax.attr(w, AS.kAXTitleAttribute) or "",
                "subrole": ax.attr(w, AS.kAXSubroleAttribute) or "",
                "pos": pos,
                "size": size,
                "main": main is not None and w == main,
                "focused": focused is not None and w == focused,
                "minimized": bool(ax.attr(w, AS.kAXMinimizedAttribute)),
                "modal": bool(ax.attr(w, "AXModal")),
            }
        )
    return out


def _pick_window(root, index: int | None, title: str | None):
    AS = ax._ax()  # noqa: N806
    windows = list(ax.attr(root, AS.kAXWindowsAttribute) or [])
    if title:
        needle = title.lower()
        windows = [w for w in windows if needle in str(ax.attr(w, AS.kAXTitleAttribute) or "").lower()]
        return windows[0] if windows else None
    if index is not None:
        return windows[index] if 0 <= index < len(windows) else None
    return ax.attr(root, AS.kAXFocusedWindowAttribute) or ax.attr(root, AS.kAXMainWindowAttribute) or (
        windows[0] if windows else None
    )


def window_op(root, pid: int, args) -> dict[str, Any]:
    AS = ax._ax()  # noqa: N806
    import Quartz

    w = _pick_window(root, args.index, args.title)
    if w is None:
        return fail("window_not_found", retry="reobserve", app=args.app)
    op = args.cmd
    refusal = gate.check(pid)
    if refusal:
        return refusal
    dry = gate.dry_run_result(f"window_{op}", title=ax.attr(w, AS.kAXTitleAttribute))
    if dry:
        return dry

    err = 0
    if op == "move":
        v = AS.AXValueCreate(AS.kAXValueCGPointType, Quartz.CGPoint(args.x, args.y))
        err = AS.AXUIElementSetAttributeValue(w, AS.kAXPositionAttribute, v)
    elif op == "resize":
        v = AS.AXValueCreate(AS.kAXValueCGSizeType, Quartz.CGSize(args.width, args.height))
        err = AS.AXUIElementSetAttributeValue(w, AS.kAXSizeAttribute, v)
    elif op == "minimize":
        err = AS.AXUIElementSetAttributeValue(w, AS.kAXMinimizedAttribute, True)
    elif op == "restore":
        err = AS.AXUIElementSetAttributeValue(w, AS.kAXMinimizedAttribute, False)
    elif op in ("raise", "focus"):
        err = AS.AXUIElementPerformAction(w, AS.kAXRaiseAction)
        AS.AXUIElementSetAttributeValue(w, AS.kAXMainAttribute, True)
        if op == "focus":
            activate(None, pid)
    elif op == "close":
        button = ax.attr(w, AS.kAXCloseButtonAttribute)
        if button is None:
            return fail("no_close_button", retry="never")
        err = AS.AXUIElementPerformAction(button, AS.kAXPressAction)
    elif op == "fullscreen":
        err = AS.AXUIElementSetAttributeValue(w, "AXFullScreen", not bool(ax.attr(w, "AXFullScreen")))
    time.sleep(0.2)
    gate.record(f"window_{op}", pid)
    return {
        "ok": err == 0,
        "action": f"window_{op}",
        "err": int(err),
        "action_sent": True,
        "window": {"pos": ax.point_of(w), "size": ax.size_of(w), "title": ax.attr(w, AS.kAXTitleAttribute) or "",
                   "minimized": bool(ax.attr(w, AS.kAXMinimizedAttribute))},
    }


# ------------------------------------------------------------------ menu
def _norm(text: str) -> str:
    return text.replace("…", "").replace("...", "").strip().lower()


# Standard AppKit menu titles in the most common localizations, so a path
# written in English ("View > Show Sidebar") also works on a Chinese system.
MENU_ALIASES: dict[str, tuple[str, ...]] = {
    "file": ("文件", "檔案", "ファイル"),
    "edit": ("编辑", "編輯", "編集"),
    "view": ("显示", "顯示", "视图", "表示"),
    "go": ("前往", "移動"),
    "window": ("窗口", "視窗", "ウインドウ"),
    "help": ("帮助", "輔助說明", "ヘルプ"),
    "format": ("格式", "フォーマット"),
    "history": ("历史记录", "歷史記錄", "履歴"),
    "bookmarks": ("书签", "書籤", "ブックマーク"),
    "tools": ("工具", "ツール"),
}


def menu_candidates(part: str) -> set[str]:
    """Pure: normalized titles that should match one path component."""
    n = _norm(part)
    out = {n}
    for english, localized in MENU_ALIASES.items():
        names = {english, *(_norm(x) for x in localized)}
        if n in names:
            out |= names
    return out


def _menu_children(el):
    """Items of a menu bar item or menu item: they live inside an AXMenu child."""
    AS = ax._ax()  # noqa: N806
    items = []
    for child in ax.attr(el, AS.kAXChildrenAttribute) or []:
        if ax.attr(child, AS.kAXRoleAttribute) == "AXMenu":
            items.extend(ax.attr(child, AS.kAXChildrenAttribute) or [])
        else:
            items.append(child)
    return items


def _item_info(el) -> dict[str, Any]:
    AS = ax._ax()  # noqa: N806
    title = ax.attr(el, AS.kAXTitleAttribute) or ""
    cmd_char = ax.attr(el, "AXMenuItemCmdChar")
    return {
        "title": title,
        "enabled": bool(ax.attr(el, AS.kAXEnabledAttribute)),
        "shortcut": str(cmd_char) if cmd_char else None,
        "submenu": any(ax.attr(c, AS.kAXRoleAttribute) == "AXMenu" for c in (ax.attr(el, AS.kAXChildrenAttribute) or [])),
    }


def split_menu_path(path: str) -> list[str]:
    """``"File > Export…"`` -> ``["File", "Export…"]`` (also accepts ``/`` and ``→``)."""
    for sep in ("→", " / "):
        path = path.replace(sep, ">")
    return [p.strip() for p in path.split(">") if p.strip()]


def menu(root, pid: int, args) -> dict[str, Any]:
    AS = ax._ax()  # noqa: N806
    bar = ax.attr(root, AS.kAXMenuBarAttribute)
    if bar is None:
        return fail("no_menu_bar", retry="never", hint="the app has no menu bar (background agent?)")
    parts = split_menu_path(args.path or "")
    current = bar
    trail: list[str] = []
    for part in parts:
        items = _menu_children(current)
        wanted = menu_candidates(part)
        target = _norm(part)
        match = next((i for i in items if _norm(str(ax.attr(i, AS.kAXTitleAttribute) or "")) in wanted), None)
        if match is None and target:
            match = next((i for i in items if target in _norm(str(ax.attr(i, AS.kAXTitleAttribute) or ""))), None)
        if match is None:
            titles = [t for t in (str(ax.attr(i, AS.kAXTitleAttribute) or "") for i in items) if t]
            return fail("menu_item_not_found", retry="never", path=trail + [part], available=titles[:60])
        trail.append(str(ax.attr(match, AS.kAXTitleAttribute) or part))
        current = match

    if args.cmd == "list":
        items = [_item_info(i) for i in _menu_children(current)]
        return {"ok": True, "path": trail, "items": [i for i in items if i["title"]]}

    if not parts:
        return fail("menu_path_required", retry="never")
    info = _item_info(current)
    if not info["enabled"]:
        return fail("menu_item_disabled", retry="reobserve", path=trail)
    refusal = gate.check(pid)
    if refusal:
        return refusal
    dry = gate.dry_run_result("menu_select", path=trail)
    if dry:
        return dry
    err = AS.AXUIElementPerformAction(current, AS.kAXPressAction)
    gate.record("menu_select", pid, path=trail)
    return {"ok": err == 0, "action": "menu_select", "err": int(err), "action_sent": True, "path": trail}


# ------------------------------------------------------------------- run
def run(args) -> int:
    group = args.group
    if group == "app":
        if args.cmd == "list":
            return _print({"apps": list_apps(args.all)})
        if args.cmd == "open":
            if not args.target:
                return _print({"error": "app open needs --target URL-or-path"}, EXIT_USAGE)
            dry = gate.dry_run_result("app_open", target=args.target)
            return _print(dry or open_target(args.target, args.app, args.background))
        if not (args.app or args.pid):
            return _print({"error": f"app {args.cmd} needs --app or --pid"}, EXIT_USAGE)
        if args.cmd == "launch":
            if not args.app:
                return _print({"error": "app launch needs --app"}, EXIT_USAGE)
            dry = gate.dry_run_result("app_launch", app=args.app)
            result = dry or launch(args.app, args.background)
            return _print(result, 0 if result.get("ok") else EXIT_NOT_FOUND)
        app = _running(args.app, args.pid)
        if app is None:
            return _print(fail("app_not_found", retry="never", app=args.app or args.pid), EXIT_NOT_FOUND)
        pid = int(app.processIdentifier())
        refusal = gate.check(pid)
        if refusal:
            return _print(refusal, EXIT_POLICY)
        dry = gate.dry_run_result(f"app_{args.cmd}", **darwin.app_info_for_pid(pid))
        if dry:
            return _print(dry)
        if args.cmd == "activate":
            return _print(activate(None, pid))
        if args.cmd == "hide":
            return _print({"ok": bool(app.hide()), "action": "hide", "action_sent": True, "pid": pid})
        if args.cmd == "quit":
            ok = bool(app.forceTerminate() if args.force else app.terminate())
            gate.record("app_quit", pid, force=bool(args.force))
            return _print({"ok": ok, "action": "quit", "force": bool(args.force), "action_sent": True, "pid": pid,
                           "hint": "" if ok else "the app refused (unsaved changes?); check for a dialog"})
        return _print({"error": f"unknown app command {args.cmd}"}, EXIT_USAGE)

    if not darwin.permissions()["accessibility"]:
        print(json.dumps({"error": "accessibility_not_granted", "hint": darwin.permission_hint("accessibility")}),
              file=sys.stderr)
        return EXIT_USAGE
    root, app = ax.app_root(args)
    if root is None:
        return _print(fail("app_not_found", retry="never", app=args.app), EXIT_NOT_FOUND)
    pid = int(app) if isinstance(app, int) else int(app.processIdentifier())

    if group == "window":
        if args.cmd == "list":
            return _print({"app": darwin.app_info_for_pid(pid), "windows": ax_windows(root)})
        if args.cmd == "move" and (args.x is None or args.y is None):
            return _print({"error": "window move needs --x/--y"}, EXIT_USAGE)
        if args.cmd == "resize" and (args.width is None or args.height is None):
            return _print({"error": "window resize needs --width/--height"}, EXIT_USAGE)
        result = window_op(root, pid, args)
        return _print(result, 0 if result.get("ok") else (EXIT_POLICY if result.get("reason") in _POLICY else EXIT_NOT_FOUND))

    if group == "menu":
        result = menu(root, pid, args)
        return _print(result, 0 if result.get("ok") else (EXIT_POLICY if result.get("reason") in _POLICY else EXIT_NOT_FOUND))
    return EXIT_USAGE


_POLICY = {"app_denied", "app_not_allowed", "sensitive_app", "screen_locked", "secure_input_active"}
