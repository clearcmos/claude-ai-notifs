#!/usr/bin/env python3
"""Unit tests for bin/claude-announce-hooks.py (settings.json wiring).

Covers the parts that edit the user's real config: structural hook matching
(exec form, legacy shell form, notify-unfocused.sh, and NOT unrelated hooks),
idempotent wiring, migration off the old form, uninstall, and the atomic write.
Stdlib only; no settings.json is touched except temp files this test creates.
"""

import importlib.util
import json
import os
import pathlib
import stat
import tempfile
import unittest

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "bin" / "claude-announce-hooks.py"
)
_spec = importlib.util.spec_from_file_location("claude_announce_hooks", _MODULE_PATH)
hooks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hooks)

ANNOUNCE = "/repo/bin/claude-announce"


def exec_entry(arg="stop", command=ANNOUNCE):
    return {"hooks": [{"type": "command", "command": command,
                       "args": [arg], "async": True}]}


def shell_entry(arg="stop", command=ANNOUNCE):
    return {"hooks": [{"type": "command", "command": command + " " + arg}]}


class IsOurs(unittest.TestCase):
    def test_exec_form_matches(self):
        self.assertTrue(hooks.is_ours(exec_entry(), ANNOUNCE))

    def test_exec_form_matches_by_basename_without_announce(self):
        # Uninstall does not know the repo path; basename must still match.
        self.assertTrue(hooks.is_ours(exec_entry()))

    def test_legacy_shell_form_matches(self):
        self.assertTrue(hooks.is_ours(shell_entry(), ANNOUNCE))
        self.assertTrue(hooks.is_ours(shell_entry()))

    def test_moved_repo_still_matches_by_basename(self):
        self.assertTrue(hooks.is_ours(exec_entry(command="/elsewhere/bin/claude-announce")))

    def test_notify_unfocused_legacy_matches(self):
        entry = {"hooks": [{"type": "command", "command": "/x/notify-unfocused.sh"}]}
        self.assertTrue(hooks.is_ours(entry))

    def test_unrelated_command_not_matched(self):
        self.assertFalse(hooks.is_ours({"hooks": [{"type": "command", "command": "prettier --write"}]}))

    def test_name_only_in_matcher_not_matched(self):
        # The old substring check on the whole entry would wrongly match this.
        entry = {"matcher": "claude-announce", "hooks": [{"type": "command", "command": "echo hi"}]}
        self.assertFalse(hooks.is_ours(entry, ANNOUNCE))

    def test_spaced_exec_path_without_known_announce(self):
        # Uninstall does not know the repo path; a spaced exec-form command
        # must still be recognized (regression: splitting on spaces missed it,
        # so uninstall left the live hook behind while deleting $BASE).
        entry = exec_entry(command="/tmp/repo with spaces/bin/claude-announce")
        self.assertTrue(hooks.is_ours(entry))


class UnwireSpacedPath(unittest.TestCase):
    def test_unwire_removes_spaced_exec_entry(self):
        s = {"hooks": {"Stop": [exec_entry(command="/a b/bin/claude-announce")]}}
        self.assertTrue(hooks.unwire(s))
        self.assertNotIn("Stop", s["hooks"])


class Wire(unittest.TestCase):
    def test_wires_async_exec_form(self):
        s = hooks.wire({}, ANNOUNCE)
        stop = s["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(stop["command"], ANNOUNCE)
        self.assertEqual(stop["args"], ["stop"])
        self.assertIs(stop["async"], True)
        ask = s["hooks"]["PreToolUse"][0]
        self.assertEqual(ask["matcher"], "^AskUserQuestion$")
        self.assertEqual(ask["hooks"][0]["args"], ["ask"])
        self.assertIs(ask["hooks"][0]["async"], True)
        permission = s["hooks"]["PermissionRequest"][0]
        self.assertNotIn("matcher", permission)
        self.assertEqual(permission["hooks"][0]["args"], ["permission"])
        self.assertIs(permission["hooks"][0]["async"], True)
        notif = s["hooks"]["Notification"][0]
        self.assertNotIn("permission_prompt", notif["matcher"])
        self.assertIn("elicitation_dialog", notif["matcher"])
        self.assertEqual(notif["hooks"][0]["args"], ["notification"])
        self.assertIs(notif["hooks"][0]["async"], True)

    def test_idempotent(self):
        s = {}
        for _ in range(3):
            hooks.wire(s, ANNOUNCE)
        for event in hooks.MANAGED_EVENTS:
            self.assertEqual(len(s["hooks"][event]), 1)

    def test_preserves_unrelated_hooks(self):
        s = {"hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "make notify"}]}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "echo keep"}]}],
        }}
        hooks.wire(s, ANNOUNCE)
        stop_cmds = [h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"]]
        self.assertIn("make notify", stop_cmds)
        self.assertIn(ANNOUNCE, stop_cmds)
        pretool_cmds = [
            h["command"]
            for entry in s["hooks"]["PreToolUse"]
            for h in entry["hooks"]
        ]
        self.assertEqual(pretool_cmds, ["echo keep", ANNOUNCE])

    def test_migrates_legacy_forms(self):
        s = {"hooks": {
            "Stop": [shell_entry("stop"), {"hooks": [{"type": "command", "command": "/x/notify-unfocused.sh"}]}],
        }}
        hooks.wire(s, ANNOUNCE)
        # legacy shell form + notify-unfocused replaced by exactly one exec entry
        self.assertEqual(len(s["hooks"]["Stop"]), 1)
        self.assertEqual(s["hooks"]["Stop"][0]["hooks"][0]["args"], ["stop"])

    def test_migrates_repo_backed_hook_to_installed_runtime(self):
        installed = "/home/u/.local/share/claude-ai-notifs/runtime/current/bin/claude-announce"
        s = {"hooks": {"Stop": [exec_entry(command="/old/repo/bin/claude-announce")]}}
        hooks.wire(s, installed)
        self.assertEqual(len(s["hooks"]["Stop"]), 1)
        self.assertEqual(s["hooks"]["Stop"][0]["hooks"][0]["command"], installed)


class Unwire(unittest.TestCase):
    def test_removes_and_drops_empty_event(self):
        s = hooks.wire({}, ANNOUNCE)
        self.assertTrue(hooks.unwire(s))
        for event in hooks.MANAGED_EVENTS:
            self.assertNotIn(event, s["hooks"])

    def test_removes_all_managed_hooks_and_keeps_unrelated_entries(self):
        s = hooks.wire({
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Write",
                    "hooks": [{"type": "command", "command": "format-file"}],
                }],
                "PermissionRequest": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "audit-permission"}],
                }],
            }
        }, ANNOUNCE)
        self.assertTrue(hooks.unwire(s))
        self.assertEqual(len(s["hooks"]["PreToolUse"]), 1)
        self.assertEqual(len(s["hooks"]["PermissionRequest"]), 1)
        self.assertEqual(
            s["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "format-file"
        )
        self.assertEqual(
            s["hooks"]["PermissionRequest"][0]["hooks"][0]["command"],
            "audit-permission",
        )

    def test_keeps_unrelated(self):
        s = {"hooks": {"Stop": [exec_entry(), {"hooks": [{"type": "command", "command": "keepme"}]}]}}
        self.assertTrue(hooks.unwire(s))
        cmds = [h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(cmds, ["keepme"])

    def test_noop_when_none(self):
        s = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "keepme"}]}]}}
        self.assertFalse(hooks.unwire(s))
        self.assertEqual(len(s["hooks"]["Stop"]), 1)

    def test_removes_legacy_shell_form(self):
        s = {"hooks": {"Stop": [shell_entry("stop")]}}
        self.assertTrue(hooks.unwire(s))
        self.assertNotIn("Stop", s["hooks"])


class WriteAtomic(unittest.TestCase):
    def test_failed_write_removes_random_temp(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with self.assertRaises(TypeError):
                hooks.write_atomic(path, {"not_json": object()})
            self.assertEqual(os.listdir(d), [])

    def test_new_file_defaults_to_private_mode(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            hooks.write_atomic(path, {"hooks": {}})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_writes_valid_json_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with open(path, "w") as f:
                f.write("{}\n")
            os.chmod(path, 0o600)
            hooks.write_atomic(path, {"hooks": {"Stop": []}})
            with open(path) as f:
                self.assertEqual(json.load(f), {"hooks": {"Stop": []}})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            # no temp files left behind
            self.assertEqual([n for n in os.listdir(d) if ".tmp." in n], [])

    def test_symlinked_settings_target_is_replaced_without_breaking_link(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            target = root / "dotfiles" / "settings.json"
            target.parent.mkdir()
            target.write_text("{}\n")
            link = root / ".claude" / "settings.json"
            link.parent.mkdir()
            link.symlink_to(target)

            hooks.write_atomic(str(link), {"hooks": {"Stop": []}})

            self.assertTrue(link.is_symlink())
            self.assertEqual(json.loads(target.read_text()), {"hooks": {"Stop": []}})
            self.assertEqual([p for p in target.parent.iterdir() if ".tmp." in p.name], [])


if __name__ == "__main__":
    unittest.main()
