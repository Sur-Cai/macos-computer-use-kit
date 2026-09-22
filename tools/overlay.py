#!/usr/bin/env python3
"""Compatibility shim. Prefer the unified CLI: see `macos-cu --help`.

Kept so existing scripts and docs that call `tools/<name>.py` keep working.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from macos_computer_use.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["overlay", *sys.argv[1:]]))
