"""Unit tests for the new pure logic: chords, policy, diffs, OCR geometry,
menu paths, config merging, and the MCP protocol surface.

None of these need a desktop, permissions, or a network.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macos_computer_use import keys, policy  # noqa: E402
from macos_computer_use.apps import split_menu_path  # noqa: E402
from macos_computer_use.ax import diff_elements, element_ref  # noqa: E402
from macos_computer_use.ocr import find_text, image_to_screen  # noqa: E402
from macos_computer_use.setup import codex_toml_block, merge_server  # noqa: E402


class TestChords:
    def test_plain_keys_and_names(self):
        assert keys.parse_chord("return") == (36, [], "return")
        assert keys.parse_chord("f5")[0] == 96

    def test_chord_string_and_flags_combine(self):
        assert keys.parse_chord("cmd+shift+t") == (17, ["cmd", "shift"], "t")
        assert keys.parse_chord("t", "cmd+shift") == (17, ["cmd", "shift"], "t")

    def test_aliases_are_canonical(self):
        assert keys.parse_chord("mod+s")[1] == ["cmd"]
        assert keys.parse_chord("option+command+i")[1] == ["alt", "cmd"]

    def test_uppercase_letter_adds_shift(self):
        assert keys.parse_chord("T") == (17, ["shift"], "t")

    def test_unknown_key_and_modifier_raise(self):
        with pytest.raises(keys.KeyError_):
            keys.parse_chord("hyper+x")
        with pytest.raises(keys.KeyError_):
            keys.parse_chord("你")

    def test_system_chords_are_detected(self):
        _c, mods, name = keys.parse_chord("ctrl+cmd+q")
        assert keys.is_system_chord(mods, name)
        _c, mods, name = keys.parse_chord("cmd+q")
        assert not keys.is_system_chord(mods, name)


class TestPolicy:
    def test_password_managers_are_refused_by_default(self):
        r = policy.check_app("com.1password.1password", "1Password", env={})
        assert r and r["reason"] == "sensitive_app" and r["action_sent"] is False and r["retry"] == "never"

    def test_sensitive_override(self):
        assert policy.check_app("com.1password.1password", "1Password", env={"MACOS_CU_ALLOW_SENSITIVE": "1"}) is None

    def test_ordinary_apps_pass(self):
        assert policy.check_app("com.apple.finder", "Finder", env={}) is None

    def test_deny_list(self):
        r = policy.check_app("com.tinyspeck.slackmacgap", "Slack", env={"MACOS_CU_DENY_APPS": "slack, com.foo"})
        assert r and r["reason"] == "app_denied"

    def test_allow_list_restricts_everything_else(self):
        env = {"MACOS_CU_ALLOW_APPS": "com.apple.finder"}
        assert policy.check_app("com.apple.finder", "Finder", env=env) is None
        assert policy.check_app("com.apple.Safari", "Safari", env=env)["reason"] == "app_not_allowed"

    def test_system_chord_gate(self):
        assert policy.check_chord(True, env={})["reason"] == "system_chord_refused"
        assert policy.check_chord(True, env={"MACOS_CU_ALLOW_SYSTEM_CHORDS": "1"}) is None
        assert policy.check_chord(False, env={}) is None

    def test_dry_run_flag(self):
        assert policy.dry_run({"MACOS_CU_DRY_RUN": "true"})
        assert not policy.dry_run({})

    def test_typed_text_is_never_logged(self):
        assert policy.redact_text("hunter2") == {"chars": 7}

    def test_audit_writes_jsonl_only_when_enabled(self, tmp_path):
        env = {"MACOS_CU_CACHE_DIR": str(tmp_path)}
        policy.audit({"action": "x"}, env=env)
        assert not (tmp_path / "audit.jsonl").exists()
        policy.audit({"action": "x"}, env={**env, "MACOS_CU_AUDIT": "1"})
        line = json.loads((tmp_path / "audit.jsonl").read_text().strip())
        assert line["action"] == "x" and "ts" in line


class TestRefsAndDiff:
    def test_ref_is_stable_and_content_derived(self):
        a = element_ref("AXButton", "", "", "Send", "", "Chat")
        assert a == element_ref("AXButton", "", "", "Send", "", "Chat")
        assert a != element_ref("AXButton", "", "", "Send", "", "Other window")
        assert len(a) == 8

    def test_diff_reports_added_removed_changed(self):
        before = [{"ref": "a", "role": "AXButton", "title": "OK", "value": None, "pos": [0, 0], "size": [10, 10]},
                  {"ref": "b", "role": "AXTextField", "title": "", "value": "hi", "pos": [0, 20], "size": [10, 10]}]
        after = [{"ref": "b", "role": "AXTextField", "title": "", "value": "hello", "pos": [0, 20], "size": [10, 10]},
                 {"ref": "c", "role": "AXButton", "title": "Cancel", "value": None, "pos": [0, 40], "size": [10, 10]}]
        d = diff_elements(before, after)
        assert d["counts"] == {"added": 1, "removed": 1, "changed": 1}
        assert d["changed"][0]["fields"] == ["value"]
        assert not d["no_change"]

    def test_identical_snapshots_are_no_change(self):
        s = [{"ref": "a", "role": "AXButton", "title": "OK", "value": None, "pos": [0, 0], "size": [1, 1]}]
        assert diff_elements(s, s)["no_change"]


class TestOcrGeometry:
    def test_vision_box_maps_to_screen_points(self):
        # 200x100 px image of a Retina window at screen (1000, 500): scale 2.
        # Vision box: bottom-left origin, normalized.
        rect = image_to_screen((0.5, 0.5, 0.25, 0.2), 200, 100, (1000, 500), 2.0)
        assert rect == [1050, 515, 25, 10]

    def test_find_text_prefers_exact_then_confidence(self):
        items = [{"text": "Send later", "confidence": 0.99}, {"text": "Send", "confidence": 0.5},
                 {"text": "Resend", "confidence": 0.9}]
        assert [i["text"] for i in find_text(items, "send")] == ["Send", "Send later", "Resend"]
        assert [i["text"] for i in find_text(items, "send", exact=True)] == ["Send"]


class TestMenuAndSetup:
    def test_menu_paths(self):
        assert split_menu_path("File > Export…") == ["File", "Export…"]
        assert split_menu_path("View → Show Sidebar") == ["View", "Show Sidebar"]
        assert split_menu_path("Edit / Find / Find…") == ["Edit", "Find", "Find…"]

    def test_english_menu_names_match_localized_menus(self):
        from macos_computer_use.apps import menu_candidates

        assert "显示" in menu_candidates("View")
        assert "view" in menu_candidates("显示")
        assert menu_candidates("Export…") == {"export"}

    def test_merge_preserves_other_servers(self):
        cfg = {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
        new, changed = merge_server(cfg, {"command": "/bin/macos-cu", "args": ["mcp"]})
        assert changed and new["mcpServers"]["other"] == {"command": "x"} and new["theme"] == "dark"
        assert cfg["mcpServers"] == {"other": {"command": "x"}}  # input untouched
        _again, changed2 = merge_server(new, {"command": "/bin/macos-cu", "args": ["mcp"]})
        assert not changed2

    def test_codex_toml_block(self):
        block = codex_toml_block(["/usr/local/bin/macos-cu", "mcp"])
        assert "[mcp_servers.macos-computer-use]" in block
        assert 'command = "/usr/local/bin/macos-cu"' in block and 'args = ["mcp"]' in block


class TestMcpProtocol:
    def _roundtrip(self, *messages, **kw):
        from macos_computer_use import mcp_server

        server = mcp_server.Server(mcp_server.select_tools(**kw))
        return [server.handle(m) for m in messages]

    def test_initialize_negotiates_version(self):
        (r,) = self._roundtrip({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2024-11-05"}})
        assert r["result"]["protocolVersion"] == "2024-11-05"
        assert r["result"]["serverInfo"]["name"] == "macos-computer-use"
        (r,) = self._roundtrip({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999"}})
        assert r["result"]["protocolVersion"] == "2025-06-18"

    def test_notifications_get_no_reply(self):
        assert self._roundtrip({"jsonrpc": "2.0", "method": "notifications/initialized"}) == [None]

    def test_tools_have_valid_schemas_and_annotations(self):
        (r,) = self._roundtrip({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = r["result"]["tools"]
        names = [t["name"] for t in tools]
        assert len(names) == len(set(names)) >= 15
        for t in tools:
            assert t["inputSchema"]["type"] == "object"
            assert set(t["annotations"]) >= {"readOnlyHint", "destructiveHint"}
            assert t["description"]

    def test_read_only_mode_drops_mutating_tools(self):
        (r,) = self._roundtrip({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, read_only=True)
        tools = r["result"]["tools"]
        assert tools and all(t["annotations"]["readOnlyHint"] for t in tools)
        assert "macos_click" not in [t["name"] for t in tools]

    def test_allow_and_deny_lists(self):
        from macos_computer_use.mcp_server import select_tools

        assert [t.name for t in select_tools(include="snapshot,macos_click")] == ["macos_snapshot", "macos_click"]
        assert "macos_click" not in [t.name for t in select_tools(exclude="click")]

    def test_unknown_method_and_tool(self):
        r1, r2 = self._roundtrip({"jsonrpc": "2.0", "id": 3, "method": "nope"},
                                 {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}})
        assert r1["error"]["code"] == -32601 and r2["error"]["code"] == -32602

    def test_missing_argument_is_a_tool_error_not_a_crash(self):
        (r,) = self._roundtrip({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                "params": {"name": "macos_click", "arguments": {"x": 1}}})
        assert r["result"]["isError"] is True

    def test_argv_builders_never_produce_shell_strings(self):
        from macos_computer_use.mcp_server import TOOLS

        by = {t.name: t for t in TOOLS}
        argv = by["macos_type"].build({"text": "$(rm -rf ~); 你好", "app": "Notes"})
        assert argv == ["input", "type", "--text", "$(rm -rf ~); 你好", "--app", "Notes"]
        assert by["macos_act"].build({"ref": "ab12cd34", "app": "X"})[:2] == ["ax", "press"]
        assert by["macos_act"].build({"action": "AXShowMenu", "ref": "r"})[-2:] == ["--name", "AXShowMenu"]
        assert by["macos_menu"].build({"app": "TextEdit", "path": "File > Save"})[:2] == ["menu", "select"]
        assert by["macos_window"].build({"action": "list", "app": "X"})[:2] == ["input", "windows"]

    def test_every_builder_parses_with_the_cli(self):
        """A tool whose argv the CLI parser rejects would fail at runtime."""
        from macos_computer_use.cli import build_parser
        from macos_computer_use.mcp_server import TOOLS

        sample = {"x": 1, "y": 2, "to_x": 3, "to_y": 4, "text": "t", "key": "cmd+l", "app": "Finder",
                  "task": "t", "expected": {}, "observed": {}}
        parser = build_parser()
        for t in TOOLS:
            parser.parse_args(t.build(dict(sample)))

    def test_serve_keeps_stdout_clean(self, monkeypatch):
        from macos_computer_use import mcp_server

        stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n{bad\n')
        stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", stdout)
        mcp_server.serve()
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert lines[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
        assert lines[1]["error"]["code"] == -32700


class TestVersionLockstep:
    def test_all_manifests_share_one_version(self):
        import re

        from macos_computer_use import __version__

        root = Path(__file__).resolve().parents[1]
        py = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M).group(1)
        versions = {
            "__init__": __version__,
            "pyproject": py,
            "pi": json.loads((root / "packages/pi/package.json").read_text())["version"],
            "dsh": json.loads((root / "packages/dsh/package.json").read_text())["version"],
            "claude-plugin": json.loads((root / "plugins/claude-code/.claude-plugin/plugin.json").read_text())["version"],
        }
        assert len(set(versions.values())) == 1, versions


class TestRefResolution:
    def test_menu_and_snapshot_refs_resolve(self, monkeypatch):
        """A ref from a menu-bar find or an --interactive snapshot must resolve
        even though the default walk skips the menu bar."""
        from macos_computer_use import ax

        def fake_walk_app(root, depth, role_filter=None, interactive=False, enhance=True, menus=None):
            out = [{"ref": "plain"}]
            if interactive:
                out.append({"ref": "snap"})
            if menus:
                out.append({"ref": "menu"})
            return out

        monkeypatch.setattr(ax, "walk_app", fake_walk_app)
        assert ax.find_by_ref(None, "menu", 4) == [{"ref": "menu"}]
        assert ax.find_by_ref(None, "snap", 4) == [{"ref": "snap"}]
        assert ax.find_by_ref(None, "gone", 4) == []


class TestSnapshotCache:
    def test_prune_keeps_newest(self, tmp_path):
        import os
        import time

        from macos_computer_use import ax

        for i in range(5):
            f = tmp_path / f"s{i}.json"
            f.write_text("{}")
            os.utime(f, (time.time() + i, time.time() + i))
        (tmp_path / "keep.txt").write_text("not a snapshot")
        ax.prune_snapshots(str(tmp_path), keep=2)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.txt", "s3.json", "s4.json"]
