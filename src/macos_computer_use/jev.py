"""Jev (TypeSafe System One) integration: semantic guards for computer use.

Two entry points, both reading JSON on stdin and printing JSON on stdout:

- ``guard``  : one request fans out several independent yes/no and choice
  judgments (right target / input correctness / blocker / next action) and the
  *code* applies thresholds. This is the highest-ROI place for a small model in
  a computer-use loop: immediately before an irreversible action.
- ``select`` : pick one element out of AX candidates, with a ``none`` escape
  hatch and a confidence gate.

Jev returns typed judgments and calibrated probabilities, not text. Policy and
side effects stay in code. API key: ``TYPESAFE_API_KEY`` or
``~/.config/typesafe/api_key``. See https://docs.typesafe.ai
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from . import darwin

API = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
# Act only when the semantic checks clear the bar (tune on your own data).
T_TARGET = float(os.environ.get("MACOS_CU_JEV_T_TARGET", "0.85"))
T_INPUT = float(os.environ.get("MACOS_CU_JEV_T_INPUT", "0.85"))


def model() -> str:
    return os.environ.get("TYPESAFE_MODEL", DEFAULT_MODEL)


def _post(body: dict[str, Any], key: str, timeout: float = 30.0) -> tuple[dict[str, Any] | None, int]:
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp), 0
    except urllib.error.HTTPError as e:
        print(json.dumps({"error": f"HTTP {e.code}", "body": e.read().decode()[:300]}), file=sys.stderr)
        return None, 3
    except urllib.error.URLError as e:
        print(json.dumps({"error": "network_error", "detail": str(e.reason)[:200]}), file=sys.stderr)
        return None, 3


def _api_key_or_exit() -> str:
    key = darwin.jev_key()
    if not key:
        print(
            json.dumps(
                {
                    "error": "TYPESAFE_API_KEY not set",
                    "hint": "export TYPESAFE_API_KEY=... or write it to ~/.config/typesafe/api_key "
                    "(keys: https://console.typesafe.ai/keys)",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
    return key


def decide(right: float, inp: float, blocker: str, nxt: str) -> str:
    """Apply the guard policy. Pure function so it can be unit-tested.

    Code owns the decision: proceed only when nothing blocks and both semantic
    checks clear their thresholds. The model may only contribute the two safe
    recoveries (they cannot send or submit anything); everything else asks the
    user.
    """
    if blocker == "none" and right >= T_TARGET and inp >= T_INPUT:
        return "proceed"
    if nxt in ("switch_target", "retype_input"):
        return nxt
    return "ask_user"


def guard(payload: dict[str, Any], key: str) -> int:
    state = {
        "task": payload.get("task", ""),
        "expected": payload.get("expected", {}),
        "observed": payload.get("observed", {}),
    }
    body = {
        "state": state,
        "model": model(),
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
                    "Does `observed.input_text` match `expected.message` (the message the task intends "
                    "to send)? Allow minor whitespace differences, but answer false for empty, unrelated, "
                    "garbled, or someone else's clipboard content."
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
    data, code = _post(body, key)
    if data is None:
        return code

    a = data.get("answers", {})
    right = a.get("right_target", {}).get("noul", 0.0)
    inp = a.get("input_ok", {}).get("noul", 0.0)
    blocker = a.get("blocker", {}).get("choice", "unknown")
    nxt = a.get("next_action", {}).get("choice", "ask_user")

    # Policy: code owns the decision. See `decide`.
    decision = decide(right, inp, blocker, nxt)

    print(json.dumps({
        "answers": {"right_target": right, "input_ok": inp, "blocker": blocker, "next_action": nxt},
        "thresholds": {"right_target": T_TARGET, "input_ok": T_INPUT},
        "decision": decision,
        "model_suggested": nxt,
        "usage": data.get("usage"),
    }, ensure_ascii=False))
    return 0


def select(payload: dict[str, Any], key: str) -> int:
    goal = payload.get("goal", "")
    candidates = payload.get("candidates", [])
    if not candidates:
        print(json.dumps({"error": "no candidates supplied"}), file=sys.stderr)
        return 2

    index = {str(c.get("id")): (c.get("text") or "") for c in candidates}
    choices = dict(index)
    choices["none"] = "No candidate matches the goal"
    body = {
        "state": {"goal": goal, "candidates": [{"id": str(c.get("id")), "text": c.get("text") or ""} for c in candidates]},
        "model": model(),
        "questions": {
            "pick": {
                "type": "choice",
                "instructions": (
                    "Which candidate is the element described by `goal`? Answer `none` when no "
                    "candidate matches. Judge by role, size, and the text/label it carries."
                ),
                "criteria": choices,
            }
        },
    }
    data, code = _post(body, key)
    if data is None:
        return code

    picked = data.get("answers", {}).get("pick", {})
    choice = str(picked.get("choice", "none"))
    probs = picked.get("probabilities", {}) or {}
    confidence = float(probs.get(choice, 0.0))

    if choice == "none" or choice not in index:
        gate = "no_match"
    elif confidence >= float(os.environ.get("MACOS_CU_JEV_SELECT_GATE", "0.7")):
        gate = "auto"
    else:
        gate = "low_confidence_review"

    print(json.dumps({
        "id": choice,
        "confidence": round(confidence, 4),
        "probabilities": {k: round(float(v), 4) for k, v in probs.items()},
        "gate": gate,
        "usage": data.get("usage"),
    }, ensure_ascii=False))
    return 0


def run(args: argparse.Namespace) -> int:
    key = _api_key_or_exit()
    payload = json.load(sys.stdin)
    return guard(payload, key) if args.cmd == "guard" else select(payload, key)
