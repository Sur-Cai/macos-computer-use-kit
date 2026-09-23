---
description: Check macOS computer-use permissions, displays, and setup
---

Call the `macos_doctor` tool from the macos-computer-use MCP server and report,
in the user's language:

1. Whether Accessibility and Screen Recording are granted. If not, name the app
   that must be enabled (from the hints) and the exact System Settings path.
2. The display layout (count, which is primary, scale) in one line.
3. Whether OCR and the optional Jev guard are available.
4. The active safety policy (dry-run, audit log, allow/deny lists).

Keep it short. If everything passes, suggest a first step such as
`macos_snapshot` on Finder.
