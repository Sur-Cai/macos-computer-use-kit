"""Unit tests for the parts that are pure logic: the Jev guard policy and the
window target signature. Both are the safety-relevant bits, so they are the ones
worth pinning down without a network or a desktop.

Run: pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macos_computer_use.darwin import target_sig  # noqa: E402
from macos_computer_use.jev import decide  # noqa: E402


class TestGuardPolicy:
    def test_proceeds_when_nothing_blocks_and_both_checks_pass(self):
        assert decide(0.99, 0.99, "none", "proceed") == "proceed"

    def test_does_not_proceed_when_a_probability_is_below_threshold(self):
        assert decide(0.40, 0.99, "none", "switch_target") == "switch_target"
        assert decide(0.99, 0.40, "none", "retype_input") == "retype_input"

    def test_a_reported_blocker_overrides_high_probabilities(self):
        # A model that says "no blocker" with high scores but reports a different
        # blocker must not be able to talk the code into proceeding.
        assert decide(0.99, 0.99, "wrong_target", "proceed") == "ask_user"
        assert decide(0.99, 0.99, "login_required", "proceed") == "ask_user"
        assert decide(0.99, 0.99, "error_dialog", "proceed") == "ask_user"
        assert decide(0.99, 0.99, "unknown", "proceed") == "ask_user"

    def test_only_safe_recoveries_may_come_from_the_model(self):
        # switch_target and retype_input cannot send or submit anything.
        assert decide(0.10, 0.90, "wrong_target", "switch_target") == "switch_target"
        assert decide(0.90, 0.10, "bad_input", "retype_input") == "retype_input"
        # Anything else escalates to the user, including "proceed" as a suggestion.
        assert decide(1.0, 1.0, "none", "ask_user") == "proceed"  # policy wins over the suggestion
        assert decide(0.10, 0.10, "bad_input", "ask_user") == "ask_user"

    def test_exactly_at_threshold_counts_as_passing(self):
        assert decide(0.85, 0.85, "none", "proceed") == "proceed"
        assert decide(0.849, 0.85, "none", "switch_target") == "switch_target"


class TestTargetSignature:
    def test_signature_is_pid_window_and_bounds(self):
        win = {"pid": 37040, "id": 12770, "bounds": [642, 244, 824, 640]}
        assert target_sig(win) == "37040:12770:642:244:824:640"

    def test_negative_origins_are_preserved(self):
        # Secondary displays left of or above the primary produce negative x/y.
        win = {"pid": 1, "id": 2, "bounds": [-537, -1440, 2560, 1440]}
        assert target_sig(win) == "1:2:-537:-1440:2560:1440"


class TestCliSurface:
    def test_parser_builds_and_lists_the_documented_groups(self):
        from macos_computer_use.cli import build_parser

        parser = build_parser()
        actions = [a for a in parser._actions if getattr(a, "choices", None)]
        groups = set(actions[0].choices)  # the `group` subparsers
        assert groups == {"ax", "input", "paste", "shot", "overlay", "jev", "doctor"}

    def test_ax_requires_an_explicit_shot_scale(self):
        from macos_computer_use.cli import build_parser

        args = build_parser().parse_args(["ax", "find", "--app", "Finder"])
        # No machine-specific default may be baked in.
        assert args.shot_scale is None
