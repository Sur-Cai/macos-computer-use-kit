"""Uniform result envelopes.

Every failure an agent sees answers three questions (idea borrowed from mature
computer-use services): *what happened* (``reason``), *may input already have
reached the app* (``action_sent``), and *what to do next* (``retry``):

- ``reobserve``  state is stale or unknown; read the UI again before acting
- ``retry``      nothing was sent; the same call may be retried as-is
- ``never``      retrying cannot help (policy refusal, bad arguments)
"""

from __future__ import annotations

import json
import sys
from typing import Any

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_CAPTURE = 4
EXIT_TARGET_CHANGED = 5
EXIT_POLICY = 6
EXIT_TIMEOUT = 7


def fail(reason: str, *, action_sent: bool = False, retry: str = "reobserve", hint: str = "", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "reason": reason, "action_sent": action_sent, "retry": retry}
    if hint:
        out["hint"] = hint
    out.update(extra)
    return out


def emit(obj: dict[str, Any], code: int = EXIT_OK, *, stream=None) -> int:
    print(json.dumps(obj, ensure_ascii=False), file=stream or sys.stdout)
    return code
