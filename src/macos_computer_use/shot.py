"""Screenshot capture with blank-frame detection.

Absorbed from ZCode's ``screenshot_blank`` / ``screenshot_bounds``: never reason
on a blank or permission-starved frame; detect it and say so. Agents that skip
this step hallucinate UI state from black pixels.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

from . import darwin


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


def run(args: argparse.Namespace) -> int:
    if args.cmd == "check":
        if not args.file:
            print(json.dumps({"error": "--file required"}), file=sys.stderr)
            return 2
        print(json.dumps(analyze(args.file), ensure_ascii=False))
        return 0

    if args.cmd == "windows":
        print(json.dumps({"windows": darwin.all_windows(args.app)}, ensure_ascii=False))
        return 0

    if not darwin.permissions()["screen_recording"]:
        print(json.dumps({"error": "screen_recording_not_granted", "hint": darwin.permission_hint("screen_recording")}), file=sys.stderr)
        return 2

    out = args.out or os.path.join(tempfile.gettempdir(), "macos-cu-shot.png")
    cmd = ["screencapture", "-x"]
    if args.window_id:
        cmd += ["-l", str(args.window_id), "-o"]
    elif args.region:
        cmd += ["-R", args.region]
    elif args.app:
        wins = [w for w in darwin.all_windows(args.app) if w["layer"] == 0 and w["bounds"][2] > 100]
        if not wins:
            print(json.dumps({"error": "no_window_for_app", "app": args.app}, ensure_ascii=False))
            return 3
        wins.sort(key=lambda w: w["bounds"][2] * w["bounds"][3], reverse=True)
        cmd += ["-l", str(wins[0]["id"]), "-o"]
    cmd.append(out)

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(out):
        print(json.dumps({"error": "capture_failed", "stderr": proc.stderr[-200:]}, ensure_ascii=False))
        return 4
    print(json.dumps(analyze(out), ensure_ascii=False))
    return 0
