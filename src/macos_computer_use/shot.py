"""Screenshot capture with blank-frame detection, crops, and set-of-mark labels.

Absorbed from ZCode's ``screenshot_blank`` / ``screenshot_bounds``: never reason
on a blank or permission-starved frame; detect it and say so. Agents that skip
this step hallucinate UI state from black pixels.

Every capture also reports where the image sits on screen (``origin``, in
global top-left points) and its ``scale`` (image pixels per point), so any pixel
in the image maps back to a clickable screen point without guessing:

    screen = origin + pixel / scale

``shot annotate`` draws numbered boxes over the interactive AX elements of a
window (set-of-mark prompting): the model says "click 7", the table says which
element and which screen point 7 is.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

from . import darwin
from .results import EXIT_CAPTURE, EXIT_NOT_FOUND, EXIT_USAGE


def analyze(path: str) -> dict:
    from PIL import Image, ImageStat

    img = Image.open(path).convert("L")
    stat = ImageStat.Stat(img)
    mean = float(stat.mean[0])
    std = float(stat.stddev[0])
    verdict = "ok"
    hint = ""
    blank = std < 2.0
    if blank and mean < 5:
        verdict = "all_black"
        hint = "screen recording permission may be missing, or the window is fully occluded"
    elif blank and mean > 250:
        verdict = "all_white"
        hint = "the window may be blank or still loading"
    elif blank:
        verdict = "uniform"
        hint = "no visual detail; check the target window state"
    return {
        "path": path,
        "width": img.width,
        "height": img.height,
        "blank": blank,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "verdict": verdict,
        "hint": hint,
    }


def _main_window(app: str) -> dict[str, Any] | None:
    wins = [w for w in darwin.all_windows(app) if w["layer"] == 0 and w["bounds"][2] > 100]
    if not wins:
        return None
    wins.sort(key=lambda w: w["bounds"][2] * w["bounds"][3], reverse=True)
    return wins[0]


def capture(out: str, app: str | None = None, window_id: int | None = None, region: str | None = None,
            display: int | None = None) -> dict[str, Any]:
    """Capture to ``out`` and describe the geometry. Returns ``ok`` + metadata."""
    cmd = ["screencapture", "-x"]
    bounds: list[int] | None = None
    win = None
    if window_id:
        win = darwin.window_info(window_id)
        cmd += ["-l", str(window_id), "-o"]
    elif region:
        try:
            bounds = [int(float(v)) for v in region.split(",")]
            assert len(bounds) == 4
        except (ValueError, AssertionError):
            return {"ok": False, "reason": "bad_region", "detail": "--region must be x,y,w,h"}
        cmd += ["-R", ",".join(str(v) for v in bounds)]
    elif app:
        win = _main_window(app)
        if win is None:
            return {"ok": False, "reason": "no_window_for_app", "app": app, "action_sent": False, "retry": "reobserve"}
        cmd += ["-l", str(win["id"]), "-o"]
    elif display is not None:
        cmd += ["-D", str(int(display) + 1)]
        for d in darwin.displays():
            if d["index"] == int(display):
                bounds = d.get("bounds")
    else:
        for d in darwin.displays():
            if d["primary"]:
                bounds = d.get("bounds")
    if win is not None:
        bounds = list(win["bounds"])
    cmd.append(out)

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(out):
        return {"ok": False, "reason": "capture_failed", "stderr": proc.stderr[-200:]}
    info = analyze(out)
    scale = 1.0
    if bounds and bounds[2]:
        scale = round(info["width"] / bounds[2], 4)
    info.update(
        ok=True,
        origin=[bounds[0], bounds[1]] if bounds else [0, 0],
        bounds=bounds,
        scale=scale,
        window=win,
    )
    return info


def crop(path: str, out: str, rect: list[int], origin: list[int], scale: float) -> dict[str, Any]:
    """Crop a screen-point rect out of a capture (a "zoom" for small UI)."""
    from PIL import Image

    x, y, w, h = rect
    box = (
        round((x - origin[0]) * scale),
        round((y - origin[1]) * scale),
        round((x - origin[0] + w) * scale),
        round((y - origin[1] + h) * scale),
    )
    with Image.open(path) as img:
        img.crop(box).save(out)
    return {"crop": out, "rect": rect, "origin": [x, y], "scale": scale}


def annotate_elements(path: str, out: str, elements: list[dict[str, Any]], origin: list[int], scale: float) -> list[dict[str, Any]]:
    """Draw numbered boxes for ``elements`` (screen-point pos/size) onto a capture."""
    from PIL import Image, ImageDraw, ImageFont

    palette = [(255, 59, 48), (0, 122, 255), (52, 199, 89), (255, 149, 0), (175, 82, 222), (255, 45, 85)]
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", max(12, int(11 * scale)))
    except OSError:
        font = ImageFont.load_default()
    marks = []
    for n, e in enumerate(elements, start=1):
        (px, py), (w, h) = e["pos"], e["size"]
        x0, y0 = (px - origin[0]) * scale, (py - origin[1]) * scale
        x1, y1 = x0 + w * scale, y0 + h * scale
        if x1 < 0 or y1 < 0 or x0 > img.width or y0 > img.height:
            continue
        color = palette[n % len(palette)]
        draw.rectangle([x0, y0, x1, y1], outline=color, width=max(2, int(scale)))
        label = str(n)
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0] + 6, tb[3] - tb[1] + 4
        lx, ly = max(0, x0), max(0, y0 - th) if y0 - th >= 0 else y0
        draw.rectangle([lx, ly, lx + tw, ly + th], fill=color)
        draw.text((lx + 3, ly + 1), label, fill=(255, 255, 255), font=font)
        marks.append(
            {
                "mark": n,
                "ref": e.get("ref"),
                "role": e.get("role"),
                "label": (e.get("title") or e.get("desc") or e.get("value") or "")[:60],
                "center_screen": [px + w // 2, py + h // 2],
            }
        )
    img.save(out)
    return marks


def _encode(path: str, max_width: int | None = None) -> dict[str, Any]:
    """Base64 PNG for harnesses that want the pixels inline (e.g. MCP)."""
    from io import BytesIO

    from PIL import Image

    with Image.open(path) as img:
        img = img.convert("RGB")
        if max_width and img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, max(1, int(img.height * ratio))))
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
    return {"mime": "image/png", "base64": base64.b64encode(buf.getvalue()).decode(), "width": img.width,
            "height": img.height}


def run(args: argparse.Namespace) -> int:
    if args.cmd == "check":
        if not args.file:
            print(json.dumps({"error": "--file required"}), file=sys.stderr)
            return EXIT_USAGE
        print(json.dumps(analyze(args.file), ensure_ascii=False))
        return 0

    if args.cmd == "windows":
        print(json.dumps({"windows": darwin.all_windows(args.app)}, ensure_ascii=False))
        return 0

    if args.cmd == "displays":
        print(json.dumps({"displays": darwin.displays()}, ensure_ascii=False))
        return 0

    if not darwin.permissions()["screen_recording"]:
        print(json.dumps({"error": "screen_recording_not_granted", "hint": darwin.permission_hint("screen_recording")}), file=sys.stderr)
        return EXIT_USAGE

    out = args.out or os.path.join(tempfile.gettempdir(), f"macos-cu-{args.cmd}.png")

    if args.cmd == "annotate":
        if not (args.app or args.pid):
            print(json.dumps({"error": "shot annotate needs --app or --pid"}), file=sys.stderr)
            return EXIT_USAGE
        return _annotate(args, out)

    cap = capture(out, app=args.app, window_id=args.window_id, region=args.region, display=args.display)
    if not cap.get("ok"):
        print(json.dumps(cap, ensure_ascii=False))
        return EXIT_NOT_FOUND if cap.get("reason") == "no_window_for_app" else EXIT_CAPTURE
    if args.crop:
        rect = [int(float(v)) for v in args.crop.split(",")]
        crop_out = out.replace(".png", "-crop.png")
        cap["crop"] = crop(out, crop_out, rect, cap["origin"], cap["scale"])
        cap["path"] = crop_out
        cap["origin"], cap["bounds"] = rect[:2], rect
    if args.base64:
        cap["image"] = _encode(cap["path"], args.max_width)
    print(json.dumps(cap, ensure_ascii=False))
    return 0


def _annotate(args, out: str) -> int:
    from . import ax

    root, app = ax.app_root(args)
    if root is None:
        print(json.dumps({"ok": False, "reason": "app_not_found", "app": args.app}, ensure_ascii=False))
        return EXIT_NOT_FOUND
    pid = int(app) if isinstance(app, int) else int(app.processIdentifier())
    name = darwin.app_info_for_pid(pid).get("name") or args.app
    cap = capture(out, app=name, window_id=args.window_id)
    if not cap.get("ok"):
        print(json.dumps(cap, ensure_ascii=False))
        return EXIT_CAPTURE
    b = cap["bounds"] or [0, 0, 10**6, 10**6]
    elements = [
        e for e in ax.walk_app(root, 24, interactive=True)
        if e["pos"] and e["size"] and e["size"][0] >= 6 and e["size"][1] >= 6
        and b[0] <= e["pos"][0] + e["size"][0] // 2 <= b[0] + b[2]
        and b[1] <= e["pos"][1] + e["size"][1] // 2 <= b[1] + b[3]
    ][: args.max]
    marks = annotate_elements(out, out, elements, cap["origin"], cap["scale"])
    cache = os.path.join(ax.snapshot_cache_dir(), f"marks-{pid}.json")
    with open(cache, "w") as fh:
        json.dump({"app": name, "elements": elements, "marks": marks}, fh, ensure_ascii=False)
    result = {"ok": True, "path": out, "origin": cap["origin"], "scale": cap["scale"], "verdict": cap["verdict"],
              "marks": marks, "snapshot": cache,
              "hint": "act on a mark with `ax press --app ... --ref <ref>` or click its center_screen"}
    if args.base64:
        result["image"] = _encode(out, args.max_width)
    print(json.dumps(result, ensure_ascii=False))
    return 0
