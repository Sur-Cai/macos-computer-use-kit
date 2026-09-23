"""macOS platform layer: guards, permissions, app/window resolution, displays.

Everything macOS-specific that more than one command needs lives here, so the
other modules stay portable and testable.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from typing import Any


def require_macos() -> None:
    """Exit with an actionable message when not running on macOS."""
    if sys.platform != "darwin":
        print(
            json.dumps(
                {
                    "error": "unsupported_platform",
                    "platform": sys.platform,
                    "detail": "this toolkit drives macOS Accessibility and CoreGraphics APIs",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _pyobjc():
    try:
        import ApplicationServices as AS  # noqa: N813
        from AppKit import NSWorkspace
        import Quartz
    except ImportError as exc:  # pragma: no cover - depends on host setup
        print(
            json.dumps(
                {
                    "error": "missing_dependency",
                    "detail": f"{exc}. Install with: pip install 'macos-computer-use-kit' "
                    "(or: pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa "
                    "pyobjc-framework-ApplicationServices)",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    return AS, NSWorkspace, Quartz


def permissions() -> dict[str, bool]:
    """Report the two TCC permissions this toolkit needs."""
    AS, _NSWorkspace, Quartz = _pyobjc()  # noqa: N806
    accessibility = bool(AS.AXIsProcessTrusted())
    try:
        screen_recording = bool(Quartz.CGPreflightScreenCaptureAccess())
    except AttributeError:  # pragma: no cover - older SDKs
        screen_recording = bool(Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
        ))
    return {"accessibility": accessibility, "screen_recording": screen_recording}


def permission_hint(kind: str) -> str:
    app = _frontmost_owner_name()
    return (
        f"{kind} permission is not granted. Open System Settings -> Privacy & Security -> "
        f"{'Accessibility' if kind == 'accessibility' else 'Screen Recording'} and enable "
        f"the process running this command{app}. Then rerun `macos-cu doctor`."
    )


def _frontmost_owner_name() -> str:
    """Best-effort hint at which app should be granted permission."""
    for candidate in (
        os.environ.get("TERM_PROGRAM"),
        os.environ.get("__CFBundleIdentifier"),
        None,
    ):
        if candidate:
            return f" ({candidate})"
    return ""


def displays() -> list[dict[str, Any]]:
    """Display geometry, in the same top-left point space AX and CGEvent use.

    ``bounds`` is ``[x, y, w, h]`` in global screen points with the origin at the
    primary display's top-left, so it can be compared directly with AX element
    positions and ``input --x/--y``. Secondary displays placed left of or above
    the primary have negative ``x``/``y``; that is normal. ``pixels`` is the
    backing-store size (``points * backing_scale`` on Retina displays).
    ``origin`` is the Cocoa (bottom-left) frame origin, kept for compatibility.
    """
    from AppKit import NSScreen

    _AS, _NSWorkspace, Quartz = _pyobjc()  # noqa: N806
    out = []
    for i, screen in enumerate(NSScreen.screens()):
        frame = screen.frame()
        scale = float(screen.backingScaleFactor())
        entry: dict[str, Any] = {
            "index": i,
            "primary": i == 0,
            "name": str(screen.localizedName()),
            "points": [int(frame.size.width), int(frame.size.height)],
            "backing_scale": int(scale) if scale.is_integer() else scale,
            "pixels": [int(frame.size.width * scale), int(frame.size.height * scale)],
            "origin": [int(frame.origin.x), int(frame.origin.y)],
        }
        try:
            display_id = int(screen.deviceDescription()["NSScreenNumber"])
            b = Quartz.CGDisplayBounds(display_id)
            entry["display_id"] = display_id
            entry["bounds"] = [int(b.origin.x), int(b.origin.y), int(b.size.width), int(b.size.height)]
        except Exception:  # pragma: no cover - defensive
            pass
        out.append(entry)
    return out


def display_for_point(x: float, y: float) -> dict[str, Any] | None:
    """The display whose top-left-space bounds contain a global point."""
    for d in displays():
        b = d.get("bounds")
        if b and b[0] <= x < b[0] + b[2] and b[1] <= y < b[1] + b[3]:
            return d
    return None


def primary_screen_point_size() -> tuple[int, int]:
    """Point size of the primary display (the AX coordinate space origin)."""
    from AppKit import NSScreen

    frame = NSScreen.screens()[0].frame()
    return int(frame.size.width), int(frame.size.height)


def find_app(name: str | None):
    """Resolve an NSRunningApplication by localized name or bundle id.

    Match order: exact bundle id, exact localized name, case-insensitive exact,
    then substring. First match in each tier wins, preferring frontmost apps.
    """
    _AS, NSWorkspace, _Quartz = _pyobjc()  # noqa: N806
    workspace = NSWorkspace.sharedWorkspace()
    if not name:
        return workspace.frontmostApplication()

    apps = list(workspace.runningApplications())
    frontmost = workspace.frontmostApplication()
    if frontmost is not None:
        apps.sort(key=lambda a: 0 if a.processIdentifier() == frontmost.processIdentifier() else 1)

    needle = name.lower()

    def field(app, getter):
        try:
            return (getter(app) or "")
        except Exception:  # pragma: no cover - defensive
            return ""

    for tier in (
        lambda a: field(a, lambda x: x.bundleIdentifier()) == name,
        lambda a: field(a, lambda x: x.localizedName()) == name,
        lambda a: field(a, lambda x: x.bundleIdentifier()).lower() == needle,
        lambda a: field(a, lambda x: x.localizedName()).lower() == needle,
        lambda a: needle in field(a, lambda x: x.bundleIdentifier()).lower(),
        lambda a: needle in field(a, lambda x: x.localizedName()).lower(),
    ):
        for app in apps:
            if tier(app):
                return app
    return None


def app_info_for_pid(pid: int) -> dict[str, Any]:
    """Bundle id and name for a pid (empty strings when unknown)."""
    try:
        from AppKit import NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
    except Exception:  # pragma: no cover - defensive
        app = None
    if app is None:
        return {"pid": int(pid), "bundle": "", "name": ""}
    return {
        "pid": int(pid),
        "bundle": str(app.bundleIdentifier() or ""),
        "name": str(app.localizedName() or ""),
    }


def secure_input_pid() -> int | None:
    """Pid of the process holding Secure Event Input (a focused password field).

    macOS turns secure input on while a password field has focus; synthetic
    keystrokes into it are exactly what an agent must not do. Returns None when
    secure input is off or the session dictionary is unavailable.
    """
    try:
        _AS, _NSWorkspace, Quartz = _pyobjc()  # noqa: N806
        session = Quartz.CGSessionCopyCurrentDictionary() or {}
        pid = session.get("kCGSSessionSecureInputPID")
        return int(pid) if pid else None
    except Exception:  # pragma: no cover - defensive
        return None


def screen_locked() -> bool:
    try:
        _AS, _NSWorkspace, Quartz = _pyobjc()  # noqa: N806
        session = Quartz.CGSessionCopyCurrentDictionary() or {}
        return bool(session.get("CGSSessionScreenIsLocked"))
    except Exception:  # pragma: no cover - defensive
        return False


def resolve_pid(app_name: str | None = None, pid: int | None = None) -> int | None:
    if pid:
        return int(pid)
    app = find_app(app_name)
    return int(app.processIdentifier()) if app is not None else None


def all_windows(owner_filter: str | None = None) -> list[dict[str, Any]]:
    """On-screen windows, main windows first."""
    _AS, _NSWorkspace, Quartz = _pyobjc()  # noqa: N806
    out = []
    for w in Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    ):
        owner = str(w.get("kCGWindowOwnerName") or "")
        if owner_filter and owner_filter.lower() not in owner.lower():
            continue
        b = w.get("kCGWindowBounds") or {}
        width, height = int(b.get("Width", 0)), int(b.get("Height", 0))
        if width < 50 or height < 50:
            continue
        out.append(
            {
                "id": int(w.get("kCGWindowNumber", 0)),
                "pid": int(w.get("kCGWindowOwnerPID", 0)),
                "owner": owner,
                "title": str(w.get("kCGWindowName") or ""),
                "bounds": [int(b.get("X", 0)), int(b.get("Y", 0)), width, height],
                "layer": int(w.get("kCGWindowLayer", 0)),
            }
        )
    out.sort(key=lambda x: (x["layer"] != 0, -(x["bounds"][2] * x["bounds"][3])))
    return out


def window_info(window_id: int) -> dict[str, Any] | None:
    for w in all_windows():
        if w["id"] == int(window_id):
            return w
    return None


def target_sig(win: dict[str, Any]) -> str:
    """Stable window identity signature: pid:wid:x:y:w:h."""
    x, y, w, h = win["bounds"]
    return f'{win["pid"]}:{win["id"]}:{x}:{y}:{w}:{h}'


def overlay_argv(x: float, y: float, label: str = "", duration: float = 1.2, color: str = "cyan") -> list[str]:
    """Command to draw an overlay ring, for the current install method."""
    return [
        sys.executable,
        "-m",
        "macos_computer_use.cli",
        "overlay",
        "show",
        "--x",
        str(int(x)),
        "--y",
        str(int(y)),
        "--label",
        label or "",
        "--duration",
        str(duration),
        "--color",
        color,
    ]


def show_overlay(x: float, y: float, label: str = "", color: str = "cyan", duration: float = 1.2) -> bool:
    """Fire-and-forget visual ring at an AX/global screen point."""
    try:
        subprocess.Popen(
            overlay_argv(x, y, label, duration, color),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:  # pragma: no cover - best-effort affordance
        return False


def macos_version() -> str:
    try:
        return platform.mac_ver()[0] or "unknown"
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def jev_key() -> str | None:
    """TypeSafe/Jev API key from the environment or the conventional files."""
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key.strip()
    for path in ("~/.config/typesafe/api_key", "~/.typesafe/api_key"):
        p = os.path.expanduser(path)
        if os.path.exists(p):
            with open(p) as fh:
                value = fh.read().strip()
            if value:
                return value
    return None
