"""Transient visual overlay: a ring (+ optional label) at a screen point.

Absorbed from Grok Bot's cursor/drag overlays: the user should be able to see
where the agent is acting. The overlay is click-through, floats above normal
windows, and fades out after ``--duration`` seconds.
"""

from __future__ import annotations

import argparse
import sys
import time

from . import darwin

COLORS = {
    "cyan": (0.20, 0.80, 1.00),
    "green": (0.20, 0.85, 0.40),
    "orange": (1.00, 0.65, 0.10),
    "red": (1.00, 0.30, 0.30),
}


def _appkit():
    darwin.require_macos()
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
        NSString,
        NSView,
        NSWindow,
        NSWindowStyleMaskBorderless,
    )
    from Foundation import NSDate, NSRunLoop

    return objc, dict(
        NSApplication=NSApplication,
        NSBackingStoreBuffered=NSBackingStoreBuffered,
        NSBezierPath=NSBezierPath,
        NSColor=NSColor,
        NSFont=NSFont,
        NSInsetRect=NSInsetRect,
        NSMakeRect=NSMakeRect,
        NSScreen=NSScreen,
        NSScreenSaverWindowLevel=NSScreenSaverWindowLevel,
        NSString=NSString,
        NSView=NSView,
        NSWindow=NSWindow,
        NSWindowStyleMaskBorderless=NSWindowStyleMaskBorderless,
        NSDate=NSDate,
        NSRunLoop=NSRunLoop,
    )


def _ring_view_class():
    objc, K = _appkit()

    class RingView(K["NSView"]):
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
            K["NSColor"].colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.95).set()
            ring = K["NSBezierPath"].bezierPathWithOvalInRect_(K["NSInsetRect"](self.bounds(), 8, 8))
            ring.setLineWidth_(5.0)
            ring.stroke()
            K["NSColor"].colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.9).set()
            dot = K["NSBezierPath"].bezierPathWithOvalInRect_(K["NSInsetRect"](self.bounds(), 30, 30))
            dot.fill()
            if self._label:
                K["NSColor"].whiteColor().set()
                attrs = {
                    "NSFont": K["NSFont"].boldSystemFontOfSize_(13),
                    "NSForegroundColor": K["NSColor"].whiteColor(),
                    "NSBackgroundColor": K["NSColor"].colorWithCalibratedWhite_alpha_(0.0, 0.65),
                }
                K["NSString"].stringWithString_(self._label).drawAtPoint_withAttributes_((4, -6), attrs)

    return RingView


def cocoa_point(ax_x: float, ax_y: float) -> tuple[float, float]:
    """Convert an AX top-left screen point to a Cocoa bottom-left window origin.

    The AX space is anchored at the primary display's top-left, so the primary
    display's height is the correct mirror axis even on multi-display setups.
    """
    _w, height = darwin.primary_screen_point_size()
    return float(ax_x), float(height - ax_y)


def show(x: float, y: float, label: str = "", duration: float = 1.5, color: str = "cyan") -> int:
    RingView = _ring_view_class()  # noqa: N806
    _objc, K = _appkit()

    app = K["NSApplication"].sharedApplication()
    app.setActivationPolicy_(1)  # accessory: no dock icon
    size = 96
    cx, cy = cocoa_point(x, y)
    frame = K["NSMakeRect"](cx - size / 2, cy - size / 2, size, size)
    win = K["NSWindow"].alloc().initWithContentRect_styleMask_backing_defer_(
        frame, K["NSWindowStyleMaskBorderless"], K["NSBackingStoreBuffered"], False
    )
    win.setOpaque_(False)
    win.setBackgroundColor_(K["NSColor"].clearColor())
    win.setLevel_(K["NSScreenSaverWindowLevel"])
    win.setIgnoresMouseEvents_(True)
    win.setHasShadow_(False)
    view = RingView.alloc().initWithFrame_(K["NSMakeRect"](0, 0, size, size))
    view.setLabel_(label or "")
    view.setRGB_(COLORS.get(color, COLORS["cyan"]))
    win.setContentView_(view)
    win.orderFrontRegardless()

    deadline = time.time() + duration
    while time.time() < deadline:
        K["NSRunLoop"].currentRunLoop().runUntilDate_(K["NSDate"].dateWithTimeIntervalSinceNow_(0.05))
    win.orderOut_(None)
    return 0


def run(args: argparse.Namespace) -> int:
    if args.cmd == "clear":
        return 0
    if args.x is None or args.y is None:
        print("--x/--y required", file=sys.stderr)
        return 2
    return show(args.x, args.y, args.label, args.duration, args.color)
