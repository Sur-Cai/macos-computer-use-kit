"""Key names, virtual key codes, and chord parsing.

Pure data and pure functions (no pyobjc), so chord handling can be unit-tested
anywhere. Codes are macOS virtual key codes for an ANSI layout; text that is not
a shortcut should go through ``input type`` (Unicode events) or ``paste``
instead, which are layout-independent.
"""

from __future__ import annotations

KEYS: dict[str, int] = {
    # letters
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32,
    "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    # digits
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29,
    # punctuation
    "=": 24, "-": 27, "]": 30, "[": 33, "'": 39, ";": 41, "\\": 42, ",": 43, "/": 44,
    ".": 47, "`": 50,
    # editing / navigation
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
    "escape": 53, "esc": 53, "forwarddelete": 117, "fwd-delete": 117,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "keypadenter": 76, "help": 114,
    # function keys
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111, "f13": 105, "f14": 107, "f15": 113,
    "f16": 106, "f17": 64, "f18": 79, "f19": 80, "f20": 90,
}

# Modifier aliases -> canonical modifier name. `mod` is the platform "primary"
# modifier (⌘ on macOS), so skills written for several OSes stay portable.
MODIFIERS: dict[str, str] = {
    "cmd": "cmd", "command": "cmd", "super": "cmd", "meta": "cmd", "mod": "cmd", "⌘": "cmd",
    "shift": "shift", "⇧": "shift",
    "ctrl": "ctrl", "control": "ctrl", "⌃": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt", "⌥": "alt",
    "fn": "fn",
}

# Canonical modifier -> Quartz flag constant name.
FLAG_CONSTANTS: dict[str, str] = {
    "cmd": "kCGEventFlagMaskCommand",
    "shift": "kCGEventFlagMaskShift",
    "ctrl": "kCGEventFlagMaskControl",
    "alt": "kCGEventFlagMaskAlternate",
    "fn": "kCGEventFlagMaskSecondaryFn",
}

# Chords that end the user's session or lock the machine. Refused unless the
# caller opts in explicitly (see policy.py).
SYSTEM_CHORDS: set[tuple[frozenset[str], str]] = {
    (frozenset({"cmd", "ctrl"}), "q"),            # lock screen
    (frozenset({"cmd", "shift"}), "q"),           # log out
    (frozenset({"cmd", "shift", "alt"}), "q"),    # log out immediately
    (frozenset({"cmd", "alt"}), "escape"),        # force quit dialog
    (frozenset({"cmd", "ctrl"}), "power"),
}


class KeyError_(ValueError):
    """Raised for an unknown key name or modifier."""


def parse_chord(key: str, flags: str = "") -> tuple[int, list[str], str]:
    """Parse ``key`` (optionally a chord like ``cmd+shift+t``) plus ``flags``.

    Returns ``(keycode, modifiers, key_name)``. Modifiers are canonical,
    de-duplicated, and sorted. A raw integer key is accepted as a keycode.
    """
    if not key:
        raise KeyError_("empty key")
    parts = [p for p in key.replace(" ", "").split("+") if p] if len(key) > 1 else [key]
    # A literal "+" key: "cmd++" or "+".
    if key.endswith("++") or key == "+":
        parts = [p for p in key[:-1].split("+") if p] + ["="]  # shift+= is "+"
    mods: set[str] = set()
    for part in parts[:-1]:
        canon = MODIFIERS.get(part.lower())
        if canon is None:
            raise KeyError_(f"unknown modifier: {part}")
        mods.add(canon)
    mods.update(parse_modifiers(flags))

    name = parts[-1]
    lowered = name.lower()
    if len(name) == 1 and name.isupper() and lowered in KEYS:
        code = KEYS[lowered]
        mods.add("shift")
    elif lowered in KEYS:
        code = KEYS[lowered]
    elif name.isdigit() and len(name) > 1:
        code = int(name)
    else:
        raise KeyError_(f"unknown key: {name}. Use `input type` for text.")
    return code, sorted(mods), lowered


def parse_modifiers(flags: str) -> list[str]:
    """Canonical modifier list from ``cmd+shift`` style flags."""
    mods: set[str] = set()
    for part in (flags.replace(" ", "").split("+") if flags else []):
        if not part:
            continue
        canon = MODIFIERS.get(part.lower())
        if canon is None:
            raise KeyError_(f"unknown modifier: {part}")
        mods.add(canon)
    return sorted(mods)


def is_system_chord(mods: list[str], key_name: str) -> bool:
    return (frozenset(mods), key_name) in SYSTEM_CHORDS
