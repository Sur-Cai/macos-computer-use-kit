#!/usr/bin/env python3
"""Screenshot capture with blank-frame detection.

Absorbed from ZCode's screenshot_blank / screenshot_bounds: never reason on a
blank or permission-starved frame; detect it and say so.

Usage:
  shot.py check --file /path/shot.png
  shot.py capture --out /tmp/s.png [--window-id N | --app "WeChat" | --region x,y,w,h]
  shot.py windows --app "WeChat"          # list window ids (for --window-id)

Output is JSON: {path,width,height,blank,mean,std,verdict,hint}
"""

import argparse
import json
import os
import subprocess
import sys

from PIL import Image, ImageStat
from Quartz import CGWindowListCopyWindowInfo, kCGNullWindowID, kCGWindowListOptionOnScreenOnly


def analyze(path):
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


def windows(app_name=None):
    out = []
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID):
        owner = str(w.get("kCGWindowOwnerName") or "")
        if app_name and app_name.lower() not in owner.lower():
            continue
        b = w.get("kCGWindowBounds") or {}
        out.append(
            {
                "id": int(w.get("kCGWindowNumber", 0)),
                "owner": owner,
                "title": str(w.get("kCGWindowName") or ""),
                "bounds": [int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0))],
                "layer": int(w.get("kCGWindowLayer", 0)),
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "capture", "windows"])
    ap.add_argument("--file")
    ap.add_argument("--out")
    ap.add_argument("--window-id", type=int)
    ap.add_argument("--app")
    ap.add_argument("--region")
    args = ap.parse_args()

    if args.cmd == "check":
        if not args.file:
            print("--file required", file=sys.stderr)
            return 2
        print(json.dumps(analyze(args.file), ensure_ascii=False))
        return 0

    if args.cmd == "windows":
        print(json.dumps({"windows": windows(args.app)}, ensure_ascii=False))
        return 0

    # capture
    out = args.out or "/tmp/shot.png"
    cmd = ["screencapture", "-x"]
    if args.window_id:
        cmd += ["-l", str(args.window_id), "-o"]
    elif args.region:
        cmd += ["-R", args.region]
    elif args.app:
        wins = [w for w in windows(args.app) if w["layer"] == 0 and w["bounds"][2] > 100]
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


if __name__ == "__main__":
    sys.exit(main())
