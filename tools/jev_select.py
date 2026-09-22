#!/usr/bin/env python3
"""Use Jev (TypeSafe System One) to pick a UI element from AX candidates.

Reads JSON on stdin:
  {"goal": "the message input box of the 联系人B chat", "candidates": [{"id": 33, "text": "AXTextArea 484x62 联系人B"}, ...]}

Prints JSON on stdout:
  {"id": 33, "confidence": 0.9, "probabilities": {...}}

Requires TYPESAFE_API_KEY (get one at https://console.typesafe.ai/keys).
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")


def api_key():
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key
    for path in ("~/.config/typesafe/api_key", "~/.typesafe/api_key"):
        p = os.path.expanduser(path)
        if os.path.exists(p):
            with open(p) as f:
                return f.read().strip()
    return None


def main():
    key = api_key()
    if not key:
        print(json.dumps({"error": "TYPESAFE_API_KEY not set (env or ~/.config/typesafe/api_key)"}), file=sys.stderr)
        return 2

    payload = json.load(sys.stdin)
    goal = payload["goal"]
    candidates = payload["candidates"]
    if not candidates:
        print(json.dumps({"error": "no candidates"}))
        return 1

    criteria = {str(c["id"]): str(c["text"])[:300] for c in candidates}
    # Best practice: always give the model an escape hatch when the candidate
    # list might not cover the input, otherwise it is forced to pick a wrong one.
    criteria["none"] = "None of the candidates matches the goal"
    body = {
        "state": {"goal": goal},
        "model": MODEL,
        "questions": {
            "pick": {
                "type": "choice",
                "instructions": (
                    "Which UI element best matches the goal? Choose exactly one id, "
                    "or 'none' when no candidate is a real match. "
                    "Return the id whose description is the closest match."
                ),
                "criteria": criteria,
            }
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

    answer = data.get("answers", {}).get("pick", {})
    result = {
        "id": answer.get("choice"),
        "confidence": answer.get("confidence"),
        "probabilities": answer.get("probabilities"),
    }
    # Confidence gate: a typed answer can still be wrong, and confidence is a
    # model signal, not authorization. Callers decide what to do with it.
    if result["id"] == "none":
        result["gate"] = "no_match"
    elif (result["confidence"] or 0) < 0.6:
        result["gate"] = "low_confidence_review"
    else:
        result["gate"] = "auto"
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
