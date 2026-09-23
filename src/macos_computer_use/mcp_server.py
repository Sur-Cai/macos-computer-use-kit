"""MCP server: ``macos-cu mcp`` exposes the toolkit to any MCP client over stdio.

Claude Code, Claude Desktop, Codex, Cursor, Gemini CLI, opencode, and every
other MCP host can drive macOS through the same verified primitives the CLI
offers. The server is dependency-free: newline-delimited JSON-RPC 2.0 on
stdin/stdout, as the MCP stdio transport specifies.

Design:

- Every tool maps onto one ``macos-cu`` argv and runs in-process with stdout
  captured, so tool results are exactly the CLI's JSON (one source of truth).
  The overlay is the exception: it runs an AppKit event loop and is always
  spawned as a child process.
- Tool arguments never touch a shell.
- ``--read-only`` exposes observation tools only; ``--tools`` / ``--exclude-tools``
  allow- and deny-list individual tools. The deterministic safety policy
  (sensitive apps, secure input, system chords, ``MACOS_CU_DRY_RUN``) applies
  to every call regardless.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
import traceback
from typing import Any, Callable

from . import __version__

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INSTRUCTIONS = """\
AX-first macOS computer use. Recommended loop:
1. macos_doctor once (permissions). 2. macos_snapshot (interactive elements with
stable #refs and exact screen geometry) — prefer it over screenshots.
3. Act semantically: macos_act (AXPress / set value by ref), macos_menu, or
macos_click at an element's center_screen. For text use macos_type (Unicode, CJK
safe). 4. Verify with macos_snapshot diff or macos_wait; use macos_screenshot
(annotate=true for numbered marks) only to verify or when AX is empty, and
macos_ocr to find text on custom-drawn UIs.
Results carry action_sent / verified / retry: never retry a non-idempotent
action when action_sent is true without re-observing first. Password managers,
auth prompts and focused password fields are refused by policy — ask the user.
"""


# --------------------------------------------------------------- schema helpers
def _s(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "string", "description": desc, **kw}


def _i(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "integer", "description": desc, **kw}


def _n(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "number", "description": desc, **kw}


def _b(desc: str) -> dict[str, Any]:
    return {"type": "boolean", "description": desc}


APP = _s("App name or bundle id, e.g. 'Safari' or 'com.apple.finder'. Omit for the frontmost app where allowed.")
PID = _i("Target process id (instead of app).")
REF = _s("Element ref from macos_snapshot (the value after '#'); survives layout changes.")
ROLE = _s("AX role filter, e.g. AXButton, AXTextField.")
TITLE = _s("Substring of the element's title / description / value.")
WINDOW_ID = _i("Window id from macos_window list; makes x/y window-relative.")


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


class Tool:
    def __init__(self, name: str, description: str, schema: dict[str, Any], build: Callable[[dict[str, Any]], list[str]],
                 *, read_only: bool, destructive: bool = False, image: bool = False, stdin_key: str | None = None,
                 title: str | None = None):
        self.name, self.description, self.schema, self.build = name, description, schema, build
        self.read_only, self.destructive, self.image, self.stdin_key = read_only, destructive, image, stdin_key
        self.title = title or name

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.read_only,
                "openWorldHint": False,
            },
        }


def _opt(argv: list[str], flag: str, value: Any) -> None:
    if value is None or value == "":
        return
    argv += [flag, str(value)]


def _flag(argv: list[str], flag: str, value: Any) -> None:
    if value:
        argv.append(flag)


def _target(a: dict[str, Any]) -> list[str]:
    argv: list[str] = []
    _opt(argv, "--app", a.get("app"))
    _opt(argv, "--pid", a.get("pid"))
    return argv


def _element(a: dict[str, Any]) -> list[str]:
    argv = _target(a)
    _opt(argv, "--ref", a.get("ref"))
    _opt(argv, "--role", a.get("role"))
    _opt(argv, "--title", a.get("title"))
    return argv


# ------------------------------------------------------------------ tool table
def _b_snapshot(a):
    argv = ["ax", "snapshot", *_target(a)]
    if a.get("interactive", True):
        argv.append("--interactive")
    _opt(argv, "--role", a.get("role"))
    _opt(argv, "--title", a.get("title"))
    _opt(argv, "--budget", a.get("budget", 6000))
    _opt(argv, "--depth", a.get("depth"))
    _opt(argv, "--diff", a.get("diff_against"))
    return argv


def _b_find(a):
    argv = ["ax", "find", "--json", *_target(a)]
    _opt(argv, "--role", a.get("role"))
    _opt(argv, "--title", a.get("title"))
    _opt(argv, "--max", a.get("max", 20))
    _opt(argv, "--depth", a.get("depth"))
    _flag(argv, "--interactive", a.get("interactive"))
    return argv


def _b_act(a):
    action = a.get("action", "press")
    cmd = {"press": "press", "set_value": "setvalue", "focus": "focus", "list_actions": "actions"}.get(action, "action")
    argv = ["ax", cmd, *_element(a)]
    if cmd == "action":
        argv += ["--name", action]
    _opt(argv, "--text", a.get("text"))
    return argv


def _b_click(a):
    argv = ["input", "click", "--x", str(a["x"]), "--y", str(a["y"]), *_target(a)]
    _opt(argv, "--window-id", a.get("window_id"))
    _opt(argv, "--expect", a.get("expect"))
    _opt(argv, "--button", a.get("button"))
    _opt(argv, "--count", a.get("count"))
    _opt(argv, "--flags", a.get("modifiers"))
    _flag(argv, "--show", a.get("show", True))
    return argv


def _b_type(a):
    if a.get("method") == "paste":
        return ["paste", "--text", a["text"], *_target(a)]
    return ["input", "type", "--text", a["text"], *_target(a)]


def _b_key(a):
    argv = ["input", "key", "--key", a["key"], *_target(a)]
    _opt(argv, "--repeat", a.get("repeat"))
    return argv


def _b_scroll(a):
    argv = ["input", "scroll", "--x", str(a["x"]), "--y", str(a["y"]), *_target(a)]
    _opt(argv, "--window-id", a.get("window_id"))
    _opt(argv, "--amount", a.get("dy", 5))
    _opt(argv, "--dx", a.get("dx"))
    _opt(argv, "--unit", a.get("unit"))
    return argv


def _b_drag(a):
    argv = ["input", "drag", "--x", str(a["x"]), "--y", str(a["y"]), "--to-x", str(a["to_x"]), "--to-y", str(a["to_y"]),
            *_target(a)]
    _opt(argv, "--window-id", a.get("window_id"))
    _opt(argv, "--button", a.get("button"))
    _opt(argv, "--steps", a.get("steps"))
    return argv


def _b_hover(a):
    argv = ["input", "hover", "--x", str(a["x"]), "--y", str(a["y"]), *_target(a)]
    _opt(argv, "--window-id", a.get("window_id"))
    return argv


def _b_app(a):
    action = a.get("action", "list")
    argv = ["app", action]
    if action == "open":
        _opt(argv, "--target", a.get("target"))
    argv += _target(a)
    _flag(argv, "--background", a.get("background"))
    _flag(argv, "--force", a.get("force"))
    _flag(argv, "--all", a.get("include_background"))
    return argv


def _b_window(a):
    action = a.get("action", "list")
    if action == "list":
        return ["input", "windows", *_target(a)]
    argv = ["window", action, *_target(a)]
    _opt(argv, "--title", a.get("title"))
    _opt(argv, "--index", a.get("index"))
    _opt(argv, "--x", a.get("x"))
    _opt(argv, "--y", a.get("y"))
    _opt(argv, "--width", a.get("width"))
    _opt(argv, "--height", a.get("height"))
    return argv


def _b_menu(a):
    argv = ["menu", "select" if a.get("path") and not a.get("list") else "list", *_target(a)]
    _opt(argv, "--path", a.get("path"))
    return argv


def _b_screenshot(a):
    if a.get("annotate"):
        argv = ["shot", "annotate", "--base64", *_target(a)]
        _opt(argv, "--max", a.get("max_marks", 80))
    else:
        argv = ["shot", "capture", "--base64", *_target(a)]
        _opt(argv, "--region", a.get("region"))
        _opt(argv, "--display", a.get("display"))
        _opt(argv, "--crop", a.get("crop"))
    _opt(argv, "--window-id", a.get("window_id"))
    _opt(argv, "--max-width", a.get("max_width", 1400))
    return argv


def _b_ocr(a):
    argv = ["ocr", *_target(a)]
    _opt(argv, "--window-id", a.get("window_id"))
    _opt(argv, "--region", a.get("region"))
    _opt(argv, "--text", a.get("text"))
    _opt(argv, "--lang", a.get("languages"))
    _opt(argv, "--max", a.get("max", 80))
    return argv


def _b_wait(a):
    argv = ["ax", "wait", *_element(a)]
    _opt(argv, "--value", a.get("value"))
    _flag(argv, "--gone", a.get("gone"))
    _opt(argv, "--timeout", a.get("timeout", 10))
    return argv


def _b_at(a):
    return ["ax", "at", "--x", str(a["x"]), "--y", str(a["y"])]


TOOLS: list[Tool] = [
    Tool("macos_doctor", "Check Accessibility / Screen Recording permissions, display layout (top-left point space, "
         "Retina scale), dependencies, OCR and Jev availability. Run first on a new machine and whenever a tool reports "
         "a permission error.", _obj({}), lambda a: ["doctor"], read_only=True, title="Doctor"),
    Tool("macos_snapshot", "Accessibility snapshot of an app: one line per element with a stable #ref, role, size, "
         "screen center and label, trimmed to a character budget. Interactive elements only by default. Pass "
         "diff_against=<snapshot path from a previous call> to get only what changed. Prefer this over screenshots.",
         _obj({"app": APP, "pid": PID, "interactive": _b("Only actionable elements (default true)."), "role": ROLE,
               "title": TITLE, "budget": _i("Max characters of output (default 6000)."), "depth": _i("Tree depth."),
               "diff_against": _s("Snapshot file path returned by an earlier call; returns a diff.")}),
         _b_snapshot, read_only=True, title="AX snapshot"),
    Tool("macos_find", "Find elements by AX role / title and return JSON with exact geometry (pos, size, "
         "center_screen) and refs.", _obj({"app": APP, "pid": PID, "role": ROLE, "title": TITLE,
         "interactive": _b("Only actionable elements."), "max": _i("Max results (default 20)."), "depth": _i("Tree depth.")}),
         _b_find, read_only=True, title="AX find"),
    Tool("macos_element_at", "Hit-test: which AX element (role, title, actions, owning app) is at a screen point.",
         _obj({"x": _n("Screen x (points)."), "y": _n("Screen y (points).")}, ["x", "y"]), _b_at, read_only=True,
         title="Element at point"),
    Tool("macos_act", "Semantic action on an element located by ref (preferred) or role+title, with read-back "
         "verification. action: press (AXPress), set_value (write text into a field), focus, list_actions, or any AX "
         "action name the element advertises (AXShowMenu, AXIncrement, AXDecrement, AXConfirm, AXCancel, AXPick, "
         "AXRaise). verified=false means fall back to macos_click on center_screen.",
         _obj({"action": _s("press | set_value | focus | list_actions | <AX action name>"), "app": APP, "pid": PID,
               "ref": REF, "role": ROLE, "title": TITLE, "text": _s("Text for set_value.")}),
         _b_act, read_only=False, destructive=True, title="AX action"),
    Tool("macos_click", "Click a screen point (or window-relative point with window_id) by posting the event to the "
         "target process — the user's cursor does not move. Pass expect (window signature from macos_window list) to "
         "refuse if the window moved. count=2 double-click, 3 triple-click; button right for context menus.",
         _obj({"x": _i("X in screen points (window-relative with window_id)."), "y": _i("Y."), "app": APP, "pid": PID,
               "window_id": WINDOW_ID, "expect": _s("Signature pid:wid:x:y:w:h; mismatch refuses."),
               "button": _s("left | right | middle", enum=["left", "right", "middle"]),
               "count": _i("1 single, 2 double, 3 triple."), "modifiers": _s("e.g. cmd, shift, cmd+shift."),
               "show": _b("Draw a ring where the click lands (default true).")}, ["x", "y"]),
         _b_click, read_only=False, destructive=True, title="Click"),
    Tool("macos_type", "Type text into the focused field of an app. method=type (default) sends Unicode key events "
         "(CJK / emoji safe, clipboard untouched); method=paste uses a clipboard-safe paste that restores the user's "
         "clipboard (better for long text). Newlines become Return — check before sending chat messages.",
         _obj({"text": _s("Text to enter."), "app": APP, "pid": PID,
               "method": _s("type | paste", enum=["type", "paste"])}, ["text"]),
         _b_type, read_only=False, destructive=True, title="Type text"),
    Tool("macos_key", "Press a key or chord, e.g. 'return', 'escape', 'cmd+l', 'cmd+shift+t', 'mod+s', 'f5'. "
         "Lock / log-out / force-quit chords are refused by policy.",
         _obj({"key": _s("Key or chord."), "app": APP, "pid": PID, "repeat": _i("Press N times.")}, ["key"]),
         _b_key, read_only=False, destructive=True, title="Key / shortcut"),
    Tool("macos_scroll", "Scroll at a point. dy>0 scrolls down, dy<0 up; dx>0 right. unit line (default) or pixel.",
         _obj({"x": _i("X."), "y": _i("Y."), "dy": _i("Vertical amount (default 5)."), "dx": _i("Horizontal amount."),
               "unit": _s("line | pixel", enum=["line", "pixel"]), "app": APP, "pid": PID, "window_id": WINDOW_ID},
              ["x", "y"]), _b_scroll, read_only=False, title="Scroll"),
    Tool("macos_drag", "Press at (x, y), drag through intermediate points to (to_x, to_y), release. For sliders, "
         "reordering, selecting ranges, moving files.",
         _obj({"x": _i("Start x."), "y": _i("Start y."), "to_x": _i("End x."), "to_y": _i("End y."), "app": APP,
               "pid": PID, "window_id": WINDOW_ID, "button": _s("left | right | middle"),
               "steps": _i("Intermediate points (default 12).")}, ["x", "y", "to_x", "to_y"]),
         _b_drag, read_only=False, destructive=True, title="Drag"),
    Tool("macos_hover", "Move the pointer (as seen by the target app) to a point, to reveal tooltips or hover menus.",
         _obj({"x": _i("X."), "y": _i("Y."), "app": APP, "pid": PID, "window_id": WINDOW_ID}, ["x", "y"]),
         _b_hover, read_only=False, title="Hover"),
    Tool("macos_app", "Apps: list running apps; launch, activate (bring to front), hide, quit (force=true to force); "
         "open a URL or file (action=open, target=..., optionally with app).",
         _obj({"action": _s("list | launch | activate | hide | quit | open",
                            enum=["list", "launch", "activate", "hide", "quit", "open"]),
               "app": APP, "pid": PID, "target": _s("URL or file path for open."),
               "background": _b("Launch/open without activating."), "force": _b("Force quit."),
               "include_background": _b("list: include menu-bar / background agents.")}),
         _b_app, read_only=False, destructive=True, title="Apps"),
    Tool("macos_window", "Windows: list (ids, owners, bounds, signatures for macos_click expect), or move / resize / "
         "minimize / restore / raise / focus / close / fullscreen a window of an app (by title substring or index; "
         "default: focused window).",
         _obj({"action": _s("list | move | resize | minimize | restore | raise | focus | close | fullscreen",
                            enum=["list", "move", "resize", "minimize", "restore", "raise", "focus", "close",
                                  "fullscreen"]),
               "app": APP, "pid": PID, "title": _s("Window title substring."), "index": _i("Window index."),
               "x": _i("move: new x."), "y": _i("move: new y."), "width": _i("resize: width."),
               "height": _i("resize: height.")}), _b_window, read_only=False, destructive=True, title="Windows"),
    Tool("macos_menu", "Menu bar by path, e.g. path='File > Export…'. list=true (or no path) lists the items at that "
         "level with enabled state and shortcuts; otherwise selects the item. Works in the background.",
         _obj({"app": APP, "pid": PID, "path": _s("Menu path separated by '>'."),
               "list": _b("List items at path instead of selecting.")}), _b_menu, read_only=False, destructive=True,
         title="Menu bar"),
    Tool("macos_screenshot", "Screenshot of an app's main window, a window id, a region 'x,y,w,h' (screen points) or a "
         "display. annotate=true draws numbered boxes on interactive elements and returns a mark table (mark -> ref, "
         "center_screen). Metadata maps image pixels to screen points: screen = origin + pixel / scale. Blank frames "
         "are flagged (verdict).",
         _obj({"app": APP, "pid": PID, "window_id": _i("Window id."), "region": _s("x,y,w,h in screen points."),
               "display": _i("Display index (see doctor)."), "crop": _s("x,y,w,h to zoom into."),
               "annotate": _b("Set-of-mark labels for interactive elements (needs app)."),
               "max_marks": _i("annotate: max labels (default 80)."),
               "max_width": _i("Downscale the returned image to this width (default 1400).")}),
         _b_screenshot, read_only=True, image=True, title="Screenshot"),
    Tool("macos_ocr", "On-device OCR (Apple Vision) of an app window / region, returning text with screen rects and "
         "centers. With text=..., returns only matches — use when the AX tree is empty (games, canvas, custom UI).",
         _obj({"app": APP, "pid": PID, "window_id": _i("Window id."), "region": _s("x,y,w,h."),
               "text": _s("Find this text."), "languages": _s("e.g. 'zh-Hans,en-US'."), "max": _i("Max items.")}),
         _b_ocr, read_only=True, title="OCR"),
    Tool("macos_wait", "Wait until an element (ref or role/title, optionally containing value) appears — or with "
         "gone=true disappears. Use after actions that load or animate instead of sleeping.",
         _obj({"app": APP, "pid": PID, "ref": REF, "role": ROLE, "title": TITLE, "value": _s("Value substring."),
               "gone": _b("Wait for disappearance."), "timeout": _n("Seconds (default 10).")}),
         _b_wait, read_only=True, title="Wait for element"),
    Tool("macos_jev_guard", "Optional semantic guard (needs TYPESAFE_API_KEY) right before an irreversible action: "
         "is this the intended target, is the input right, what blocks. Returns decision proceed / switch_target / "
         "retype_input / ask_user — the code decides, not the model.",
         _obj({"task": _s("What the user asked for."), "expected": {"type": "object", "description": "e.g. {recipient, message}"},
               "observed": {"type": "object", "description": "e.g. {chat_title, input_text}"}}, ["task", "expected", "observed"]),
         lambda a: ["jev", "guard"], read_only=True, stdin_key="__payload__", title="Jev guard"),
]

READ_ONLY = {t.name for t in TOOLS if t.read_only}


# ------------------------------------------------------------------- execution
_LOCK = threading.Lock()


def run_cli(argv: list[str], stdin_text: str | None = None) -> tuple[int, str, str]:
    """Run ``cli.main(argv)`` in-process, capturing stdout/stderr."""
    from . import cli

    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    with _LOCK:
        try:
            if stdin_text is not None:
                sys.stdin = io.StringIO(stdin_text)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = cli.main(argv)
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else 2
        finally:
            sys.stdin = old_stdin
    return int(code or 0), out.getvalue(), err.getvalue()


def call_tool(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        argv = tool.build(arguments)
    except KeyError as exc:
        return {"content": [{"type": "text", "text": f"missing required argument: {exc}"}], "isError": True}
    stdin_text = None
    if tool.stdin_key:
        stdin_text = json.dumps({k: arguments.get(k) for k in ("task", "expected", "observed")}, ensure_ascii=False)
    try:
        code, out, err = run_cli(argv, stdin_text)
    except Exception as exc:  # pragma: no cover - defensive
        return {"content": [{"type": "text", "text": f"internal error: {exc}\n{traceback.format_exc()[-800:]}"}],
                "isError": True}

    content: list[dict[str, Any]] = []
    text = out.strip()
    if tool.image and text.startswith("{"):
        try:
            payload = json.loads(text)
            image = payload.pop("image", None)
            if image:
                # Downscaling changes pixels-per-point; report the scale of the returned image.
                if payload.get("bounds") and payload["bounds"][2]:
                    payload["returned_image_scale"] = round(image["width"] / payload["bounds"][2], 4)
                content.append({"type": "image", "data": image["base64"], "mimeType": image["mime"]})
            text = json.dumps(payload, ensure_ascii=False)
        except ValueError:
            pass
    if not text:
        text = err.strip() or "{}"
    elif err.strip() and code != 0:
        text += "\n" + err.strip()
    content.insert(0, {"type": "text", "text": text})
    # Exit 1 from doctor only means a permission is missing: still a useful result.
    is_error = code not in (0, 1) or (code == 1 and tool.name != "macos_doctor")
    return {"content": content, "isError": is_error}


# -------------------------------------------------------------------- protocol
class Server:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if mid is None:  # notification
            return None
        try:
            if method == "initialize":
                requested = params.get("protocolVersion")
                version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
                result = {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "macos-computer-use", "title": "macOS Computer Use Kit", "version": __version__},
                    "instructions": SERVER_INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t.spec() for t in self.tools.values()]}
            elif method == "tools/call":
                tool = self.tools.get(params.get("name", ""))
                if tool is None:
                    return _error(mid, -32602, f"unknown tool: {params.get('name')}")
                result = call_tool(tool, params.get("arguments") or {})
            elif method in ("resources/list",):
                result = {"resources": []}
            elif method in ("prompts/list",):
                result = {"prompts": []}
            else:
                return _error(mid, -32601, f"method not found: {method}")
        except Exception as exc:  # pragma: no cover - defensive
            return _error(mid, -32603, f"internal error: {exc}")
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def select_tools(read_only: bool = False, include: str | None = None, exclude: str | None = None) -> list[Tool]:
    """Pure: the tool list after --read-only / --tools / --exclude-tools filters."""
    chosen = [t for t in TOOLS if (t.read_only or not read_only)]
    if include:
        wanted = {n.strip() for n in include.split(",") if n.strip()}
        chosen = [t for t in chosen if t.name in wanted or t.name.removeprefix("macos_") in wanted]
    if exclude:
        drop = {n.strip() for n in exclude.split(",") if n.strip()}
        chosen = [t for t in chosen if t.name not in drop and t.name.removeprefix("macos_") not in drop]
    return chosen


def serve(read_only: bool = False, include: str | None = None, exclude: str | None = None) -> int:
    read_only = read_only or os.environ.get("MACOS_CU_MCP_READ_ONLY", "").lower() in ("1", "true", "yes")
    server = Server(select_tools(read_only, include or os.environ.get("MACOS_CU_MCP_TOOLS"),
                                 exclude or os.environ.get("MACOS_CU_MCP_EXCLUDE_TOOLS")))
    # The protocol owns stdout: anything else printed there would corrupt it.
    proto_out = sys.stdout
    sys.stdout = sys.stderr
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply: Any = _error(None, -32700, "parse error")
        else:
            if isinstance(msg, list):
                reply = [r for r in (server.handle(m) for m in msg) if r is not None] or None
            else:
                reply = server.handle(msg)
        if reply is not None:
            proto_out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            proto_out.flush()
    return 0
