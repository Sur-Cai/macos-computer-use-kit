"""Pre-action gate shared by every command that sends input.

Order matters: the cheap, deterministic refusals run before anything is posted.

1. screen locked                -> ``screen_locked``
2. app policy (allow/deny/sensitive, see policy.py) -> ``app_denied`` / ...
3. typing while a password field holds Secure Event Input -> ``secure_input_active``
4. system chords (lock / log out / force quit)      -> ``system_chord_refused``

Dry-run and audit logging also live here so that every mutating command gets
them the same way.
"""

from __future__ import annotations

from typing import Any

from . import darwin, policy


def check(pid: int | None, *, typing: bool = False, system_chord: bool = False) -> dict[str, Any] | None:
    """Return a refusal envelope, or None when the action may proceed."""
    if darwin.screen_locked():
        return {
            "ok": False,
            "reason": "screen_locked",
            "detail": "the screen is locked; input would go to the login window",
            "action_sent": False,
            "retry": "never",
        }
    info = darwin.app_info_for_pid(pid) if pid else {"bundle": "", "name": ""}
    refusal = policy.check_app(info.get("bundle"), info.get("name"))
    if refusal:
        return refusal
    if typing and pid:
        secure = darwin.secure_input_pid()
        if secure and secure == int(pid):
            return {
                "ok": False,
                "reason": "secure_input_active",
                "detail": "a password field in the target app has Secure Event Input; "
                "ask the user to type secrets themselves",
                "action_sent": False,
                "retry": "never",
            }
    refusal = policy.check_chord(system_chord)
    if refusal:
        return refusal
    return None


def dry_run_result(action: str, **details: Any) -> dict[str, Any] | None:
    """When MACOS_CU_DRY_RUN=1, the result to return instead of acting."""
    if not policy.dry_run():
        return None
    return {"ok": True, "dry_run": True, "action": action, "action_sent": False, **details}


def record(action: str, pid: int | None, **details: Any) -> None:
    info = darwin.app_info_for_pid(pid) if pid else {}
    policy.audit({"action": action, "pid": pid, "bundle": info.get("bundle"), **details})
