#!/usr/bin/env python3
"""Pre-action guard: one Jev call, several independent judgments (fan-out).

Absorbed from the Jev best practices: ask every independent question against
the same state in ONE request, then let code apply thresholds. This is the
highest-ROI place to use Jev in a computer-use loop: right before an
irreversible action (sending a message, submitting a form, clicking pay).

Reads JSON on stdin:
  {"task": "...", "expected": {...}, "observed": {...}}

Prints JSON with answers + a decision computed by thresholds.

Usage:
  echo '{"task":"给联系人A发BTC行情","expected":{"recipient":"联系人A"},"observed":{"chat_title":"另一个会话","input_text":"..."}}' | guard.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")
# thresholds: act only when the semantic checks clear the bar
T_TARGET = 0.85
T_INPUT = 0.85


def api_key():
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key
    for path in ("~/.config/typesafe/api_key", "~/.typesafe/api_key"):
        p = os.path.expanduser(path)
        if os.path.exists(p):
            return open(p).read().strip()
    return None


def main():
    key = api_key()
    if not key:
        print(json.dumps({"error": "TYPESAFE_API_KEY not set"}), file=sys.stderr)
        return 2

    payload = json.load(sys.stdin)
    state = {
        "task": payload.get("task", ""),
        "expected": payload.get("expected", {}),
        "observed": payload.get("observed", {}),
    }

    body = {
        "state": state,
        "model": MODEL,
        "questions": {
            "right_target": {
                "type": "noul",
                "instructions": (
                    "Is the observed target (chat_title / window_title) the same logical target "
                    "the task intends (expected)? Ignore cosmetic differences; answer about identity."
                ),
                "criteria": {
                    "true": "observed target is the intended recipient/window",
                    "false": "observed target is a different recipient/window",
                },
            },
            "input_ok": {
                "type": "noul",
                "instructions": (
                    "Does `observed.input_text` match `expected.message` (the message the task intends to send)? "
                    "Allow minor whitespace differences, but answer false for empty, unrelated, garbled, "
                    "or someone else's clipboard content."
                ),
                "criteria": {
                    "true": "observed input is the intended message",
                    "false": "observed input differs from expected.message, or is empty/unrelated/garbled",
                },
            },
            "blocker": {
                "type": "choice",
                "instructions": "What, if anything, blocks proceeding with the action?",
                "criteria": {
                    "none": "Nothing blocks; safe to proceed",
                    "wrong_target": "The active chat/window is not the intended target",
                    "bad_input": "The input content is wrong, empty, or not the intended text",
                    "login_required": "A login or permission screen is showing",
                    "error_dialog": "An error or unexpected dialog is in the way",
                    "unknown": "Not enough evidence to tell",
                },
            },
            "next_action": {
                "type": "choice",
                "instructions": "What should the agent do next?",
                "criteria": {
                    "proceed": "Target and input are correct; perform the action",
                    "switch_target": "Switch to the intended target first, then re-check",
                    "retype_input": "Clear the input and re-enter the intended text",
                    "ask_user": "Stop and ask the user",
                },
            },
        },
    }

    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        print(json.dumps({"error": f"HTTP {e.code}", "body": e.read().decode()[:300]}), file=sys.stderr)
        return 3

    a = data.get("answers", {})
    right = a.get("right_target", {}).get("noul", 0.0)
    inp = a.get("input_ok", {}).get("noul", 0.0)
    blocker = a.get("blocker", {}).get("choice", "unknown")
    nxt = a.get("next_action", {}).get("choice", "ask_user")

    # policy: code owns the decision. A bounded set of safe recoveries may come
    # from the model (they cannot send/submit anything); everything else asks the user.
    if blocker == "none" and right >= T_TARGET and inp >= T_INPUT:
        decision = "proceed"
    elif nxt in ("switch_target", "retype_input"):
        decision = nxt
    else:
        decision = "ask_user"

    print(json.dumps({
        "answers": {
            "right_target": right,
            "input_ok": inp,
            "blocker": blocker,
            "next_action": nxt,
        },
        "thresholds": {"right_target": T_TARGET, "input_ok": T_INPUT},
        "decision": decision,
        "model_suggested": nxt,
        "usage": data.get("usage"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
