"""Deterministic safety policy: sensitive apps, system chords, dry-run, audit.

This is the first safety stage, and it is pure code: no model, no network. The
optional Jev guard is a second stage for semantic questions that rules cannot
answer. Everything here is a pure function of its inputs (environment values are
passed in), so the policy can be unit-tested without a desktop.

Environment knobs:

- ``MACOS_CU_DENY_APPS``   extra bundle ids / names to refuse (comma separated)
- ``MACOS_CU_ALLOW_APPS``  when set, *only* these apps may receive input
- ``MACOS_CU_ALLOW_SENSITIVE=1``  lift the built-in sensitive-app deny list
- ``MACOS_CU_ALLOW_SYSTEM_CHORDS=1``  allow lock / log-out / force-quit chords
- ``MACOS_CU_DRY_RUN=1``   resolve targets and report, but post no events
- ``MACOS_CU_AUDIT=1``     append one JSON line per mutating action to the audit
  log (typed text is recorded by length only, never verbatim)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping

# Apps whose UI holds secrets or system authority. Input is refused by default:
# an agent has no business typing into a password manager or an auth prompt.
SENSITIVE_BUNDLES: frozenset[str] = frozenset(
    {
        "com.1password.1password",
        "com.agilebits.onepassword7",
        "com.bitwarden.desktop",
        "com.lastpass.lastpassmacdesktop",
        "com.dashlane.dashlanephonefinal",
        "com.nordpass.macos.nordpass",
        "com.apple.keychainaccess",
        "com.apple.Passwords",
        "com.apple.SecurityAgent",
        "com.apple.LocalAuthentication.UIAgent",
        "com.apple.loginwindow",
        "com.apple.systempreferences.security",
    }
)
SENSITIVE_NAME_HINTS: tuple[str, ...] = (
    "1password", "bitwarden", "lastpass", "dashlane", "nordpass", "keychain access",
    "securityagent", "passwords",
)

# AX roles/subroles whose value must never be read out or logged.
SECURE_ROLES: frozenset[str] = frozenset({"AXSecureTextField"})
REDACTED = "«redacted»"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> list[str]:
    return [v.strip().lower() for v in (value or "").split(",") if v.strip()]


def _matches(bundle: str, name: str, needles: list[str]) -> bool:
    b, n = bundle.lower(), name.lower()
    return any(x == b or x == n for x in needles)


def check_app(bundle: str | None, name: str | None, env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """Return a refusal dict when input to this app is not allowed, else None."""
    env = os.environ if env is None else env
    bundle, name = bundle or "", name or ""
    allow = _csv(env.get("MACOS_CU_ALLOW_APPS"))
    if allow and not _matches(bundle, name, allow):
        return {
            "ok": False,
            "reason": "app_not_allowed",
            "app": name or bundle,
            "detail": "MACOS_CU_ALLOW_APPS is set and does not include this app",
            "action_sent": False,
            "retry": "never",
        }
    if _matches(bundle, name, _csv(env.get("MACOS_CU_DENY_APPS"))):
        return {
            "ok": False,
            "reason": "app_denied",
            "app": name or bundle,
            "detail": "listed in MACOS_CU_DENY_APPS",
            "action_sent": False,
            "retry": "never",
        }
    if not _truthy(env.get("MACOS_CU_ALLOW_SENSITIVE")) and is_sensitive(bundle, name):
        return {
            "ok": False,
            "reason": "sensitive_app",
            "app": name or bundle,
            "detail": "password managers, auth prompts and the login window are refused by default; "
            "ask the user to do this step (override: MACOS_CU_ALLOW_SENSITIVE=1)",
            "action_sent": False,
            "retry": "never",
        }
    return None


def is_sensitive(bundle: str | None, name: str | None) -> bool:
    b, n = (bundle or "").lower(), (name or "").lower()
    if any(b == s.lower() for s in SENSITIVE_BUNDLES):
        return True
    return any(h == n or (h in n and len(h) > 8) for h in SENSITIVE_NAME_HINTS)


def check_chord(is_system: bool, env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    env = os.environ if env is None else env
    if is_system and not _truthy(env.get("MACOS_CU_ALLOW_SYSTEM_CHORDS")):
        return {
            "ok": False,
            "reason": "system_chord_refused",
            "detail": "lock / log-out / force-quit shortcuts are refused "
            "(override: MACOS_CU_ALLOW_SYSTEM_CHORDS=1)",
            "action_sent": False,
            "retry": "never",
        }
    return None


def dry_run(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return _truthy(env.get("MACOS_CU_DRY_RUN"))


def redact_text(text: str | None) -> dict[str, Any]:
    """What the audit log keeps of typed/pasted text: its size, never content."""
    return {"chars": len(text or "")}


def audit_path(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    base = env.get("MACOS_CU_CACHE_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "macos-computer-use")
    return os.path.join(base, "audit.jsonl")


def audit(event: dict[str, Any], env: Mapping[str, str] | None = None) -> None:
    """Append one JSON line when ``MACOS_CU_AUDIT=1``. Never raises."""
    env = os.environ if env is None else env
    if not _truthy(env.get("MACOS_CU_AUDIT")):
        return
    try:
        path = audit_path(env)
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        record = {"ts": round(time.time(), 3), **event}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - audit must never break an action
        pass
