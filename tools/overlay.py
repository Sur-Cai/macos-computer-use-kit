#!/usr/bin/env python3
"""Transient visual overlay: a ring (+ optional label) at a screen point.

Absorbed from Grok Bot's CUCursorOverlayWindowSnapshot / CUDragOverlayView:
the user should be able to see where the agent is acting.

Coordinates are AX/global screen points (top-left origin). The overlay is
click-through, floats above normal windows, and fades out after --duration.

Usage:
  overlay.py show --x 1417 --y 850 [--label "发送"] [--duration 1.5] [--color cyan]
  overlay.py clear
"""

import argparse
import sys
import time

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSFont,
    NSInsetRect,
    NSMakeRect,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSStatusWindowLevel,
    NSString,
    NSView,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSDate, NSRunLoop

COLORS = {
    "cyan": (0.20, 0.80, 1.00),
    "green": (0.20, 0.85, 0.40),
    "orange": (1.00, 0.65, 0.10),
    "red": (1.00, 0.30, 0.30),
}


class RingView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(RingView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._label = ""
        self._rgb = COLORS["cyan"]
        return self

    def setLabel_(self, label):
        self._label = label

    def setRGB_(self, rgb):
        self._rgb = rgb

    def drawRect_(self, rect):
        r, g, b = self._rgb
        NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.95).set()
        ring = NSBezierPath.bezierPathWithOvalInRect_(NSInsetRect(self.bounds(), 8, 8))
        ring.setLineWidth_(5.0)
        ring.stroke()
        # center dot
        NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.9).set()
        dot = NSBezierPath.bezierPathWithOvalInRect_(NSInsetRect(self.bounds(), 30, 30))
        dot.fill()
        if self._label:
            NSColor.whiteColor().set()
            attrs = {
                "NSFont": NSFont.boldSystemFontOfSize_(13),
                "NSForegroundColor": NSColor.whiteColor(),
                "NSBackgroundColor": NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.65),
            }
            NSString.stringWithString_(self._label).drawAtPoint_withAttributes_((4, -6), attrs)


def cocoa_point(ax_x, ax_y):
    """Convert AX top-left screen point to Cocoa bottom-left window origin."""
    screen = NSScreen.screens()[0]
    height = screen.frame().size.height
    return float(ax_x), float(height - ax_y)


def show(x, y, label, duration, color):
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)  # accessory: no dock icon
    size = 96
    cx, cy = cocoa_point(x, y)
    frame = NSMakeRect(cx - size / 2, cy - size / 2, size, size)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
    )
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setLevel_(NSScreenSaverWindowLevel)
    win.setIgnoresMouseEvents_(True)
    win.setHasShadow_(False)
    view = RingView.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
    view.setLabel_(label or "")
    view.setRGB_(COLORS.get(color, COLORS["cyan"]))
    win.setContentView_(view)
    win.orderFrontRegardless()

    deadline = time.time() + duration
    while time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
    win.orderOut_(None)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "clear"])
    ap.add_argument("--x", type=int)
    ap.add_argument("--y", type=int)
    ap.add_argument("--label", default="")
    ap.add_argument("--duration", type=float, default=1.5)
    ap.add_argument("--color", default="cyan")
    args = ap.parse_args()
    if args.cmd == "clear":
        return 0
    if args.x is None or args.y is None:
        print("--x/--y required", file=sys.stderr)
        return 2
    return show(args.x, args.y, args.label, args.duration, args.color)


if __name__ == "__main__":
    sys.exit(main())
