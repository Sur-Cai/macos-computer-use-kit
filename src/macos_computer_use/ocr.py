"""On-device OCR with Apple's Vision framework — the fallback when AX is empty.

Custom-drawn UIs (games, canvas apps, some Electron and chat apps) expose little
or nothing through accessibility. Vision's text recognizer runs locally, costs
nothing, and returns boxes we convert back to global screen points, so an agent
can still target "the Send button" without a vision model.

No extra dependency: when ``pyobjc-framework-Vision`` is not installed, the
system Vision.framework is loaded directly through pyobjc-core.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

from . import darwin
from .results import EXIT_CAPTURE, EXIT_NOT_FOUND, EXIT_USAGE, fail

_VISION: dict[str, Any] = {}


def _vision():
    if _VISION:
        return _VISION
    try:
        import Vision  # type: ignore[import-not-found]

        _VISION.update(
            VNRecognizeTextRequest=Vision.VNRecognizeTextRequest,
            VNImageRequestHandler=Vision.VNImageRequestHandler,
        )
    except ImportError:
        import objc

        # Without the wrapper package, the NSError** out-parameter needs metadata.
        objc.registerMetaDataForSelector(
            b"VNImageRequestHandler",
            b"performRequests:error:",
            {"arguments": {3: {"type_modifier": objc._C_OUT}}},
        )
        ns: dict[str, Any] = {}
        objc.loadBundle("Vision", ns, bundle_path="/System/Library/Frameworks/Vision.framework")
        _VISION.update(
            VNRecognizeTextRequest=objc.lookUpClass("VNRecognizeTextRequest"),
            VNImageRequestHandler=objc.lookUpClass("VNImageRequestHandler"),
        )
    return _VISION


def image_to_screen(box: tuple[float, float, float, float], img_w: int, img_h: int,
                    origin: tuple[float, float], scale: float) -> list[int]:
    """Convert a Vision normalized box (bottom-left origin) to screen points.

    Pure function. ``origin`` is the screen point of the image's top-left and
    ``scale`` is image pixels per screen point (2.0 for a Retina capture).
    Returns ``[x, y, w, h]`` in global top-left screen points.
    """
    bx, by, bw, bh = box
    px = bx * img_w
    py = (1.0 - by - bh) * img_h
    return [
        round(origin[0] + px / scale),
        round(origin[1] + py / scale),
        round(bw * img_w / scale),
        round(bh * img_h / scale),
    ]


def recognize(path: str, languages: list[str] | None = None, fast: bool = False) -> list[dict[str, Any]]:
    """Text observations in an image: ``[{text, confidence, box}]`` (box normalized)."""
    from Foundation import NSURL, NSDictionary

    V = _vision()  # noqa: N806
    results: list[dict[str, Any]] = []
    # The accurate recognizer can be unavailable in restricted sandboxes; fall
    # back to the fast one rather than returning nothing.
    for level in ((1,) if fast else (0, 1)):
        req = V["VNRecognizeTextRequest"].alloc().init()
        req.setRecognitionLevel_(level)
        req.setUsesLanguageCorrection_(level == 0)
        if languages:
            try:
                req.setRecognitionLanguages_(languages)
            except Exception:  # pragma: no cover - older macOS
                pass
        handler = V["VNImageRequestHandler"].alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(os.path.abspath(path)), NSDictionary.dictionary()
        )
        ok = handler.performRequests_error_([req], None)
        ok = ok[0] if isinstance(ok, tuple) else ok
        if not ok:
            continue
        for obs in req.results() or []:
            cands = obs.topCandidates_(1)
            if not cands:
                continue
            bb = obs.boundingBox()
            results.append(
                {
                    "text": str(cands[0].string()),
                    "confidence": round(float(cands[0].confidence()), 3),
                    "box": (float(bb.origin.x), float(bb.origin.y), float(bb.size.width), float(bb.size.height)),
                    "level": "accurate" if level == 0 else "fast",
                }
            )
        break
    return results


def find_text(items: list[dict[str, Any]], needle: str, exact: bool = False) -> list[dict[str, Any]]:
    """Pure: filter OCR items by text (case-insensitive), best matches first."""
    n = needle.strip().lower()
    hits = []
    for it in items:
        t = it["text"].strip().lower()
        if (t == n) if exact else (n in t):
            hits.append((0 if t == n else 1, -it.get("confidence", 0), it))
    return [h[2] for h in sorted(hits, key=lambda h: (h[0], h[1]))]


def run(args) -> int:
    from . import shot

    languages = [s.strip() for s in (args.lang or "").split(",") if s.strip()] or None
    cleanup = None
    if args.file:
        path, origin, scale = args.file, (0.0, 0.0), 1.0
        if args.origin:
            ox, oy = (float(v) for v in args.origin.split(","))
            origin = (ox, oy)
        if args.scale:
            scale = float(args.scale)
    else:
        if not (args.app or args.window_id or args.region):
            print(json.dumps({"error": "ocr needs --file, --app, --window-id or --region"}), file=sys.stderr)
            return EXIT_USAGE
        if not darwin.permissions()["screen_recording"]:
            print(json.dumps({"error": "screen_recording_not_granted",
                              "hint": darwin.permission_hint("screen_recording")}), file=sys.stderr)
            return EXIT_USAGE
        fd, path = tempfile.mkstemp(prefix="macos-cu-ocr-", suffix=".png")
        os.close(fd)
        cleanup = path
        cap = shot.capture(path, app=args.app, window_id=args.window_id, region=args.region)
        if not cap.get("ok"):
            print(json.dumps(cap, ensure_ascii=False))
            return EXIT_NOT_FOUND if cap.get("reason") == "no_window_for_app" else EXIT_CAPTURE
        origin, scale = tuple(cap["origin"]), float(cap["scale"])

    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
        items = recognize(path, languages, fast=args.fast)
    finally:
        if cleanup and not args.keep:
            try:
                os.remove(cleanup)
            except OSError:
                pass

    out = []
    for it in items:
        rect = image_to_screen(it["box"], w, h, origin, scale)
        out.append({"text": it["text"], "confidence": it["confidence"], "rect": rect,
                    "center_screen": [rect[0] + rect[2] // 2, rect[1] + rect[3] // 2]})

    if args.text:
        hits = find_text(out, args.text, args.exact)
        if not hits:
            print(json.dumps(fail("text_not_found", retry="reobserve", text=args.text,
                                  seen=[o["text"] for o in out][:40]), ensure_ascii=False))
            return EXIT_NOT_FOUND
        print(json.dumps({"ok": True, "text": args.text, "matches": hits[: args.max]}, ensure_ascii=False))
        return 0

    print(json.dumps({"ok": True, "count": len(out), "image": [w, h], "origin": list(origin), "scale": scale,
                      "items": out[: args.max], "saved": cleanup if (cleanup and args.keep) else None},
                     ensure_ascii=False))
    return 0


def available() -> bool:
    try:
        darwin._pyobjc()
        _vision()
        return True
    except Exception:
        return False
