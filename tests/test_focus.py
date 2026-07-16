#!/usr/bin/env python3
"""Unit tests for terminal focus-query parsing."""

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "bin"
    / "claude-announce-focus.py"
)
_spec = importlib.util.spec_from_file_location("claude_announce_focus", _MODULE_PATH)
focus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(focus)


class WezTermFocus(unittest.TestCase):
    def test_focused_pane(self):
        self.assertEqual(
            focus.wezterm_focused_pane([{}, {"focused_pane_id": 42}]), "42")

    def test_missing_or_invalid_clients_fail_open(self):
        self.assertEqual(focus.wezterm_focused_pane([]), "")
        self.assertEqual(focus.wezterm_focused_pane({}), "")

    def test_maps_tty_basename_to_pane(self):
        panes = [
            {"pane_id": 7, "tty_name": "/dev/ttys007"},
            {"pane_id": 8, "tty_name": "/dev/ttys008"},
        ]
        self.assertEqual(focus.wezterm_pane_for_tty(panes, "ttys008"), "8")
        self.assertEqual(focus.wezterm_pane_for_tty(panes, "/dev/ttys999"), "")


class KittyFocus(unittest.TestCase):
    def test_matches_focused_window_in_focused_os_window(self):
        data = [{
            "is_focused": True,
            "tabs": [{"windows": [
                {"id": 10, "is_focused": False},
                {"id": 11, "is_focused": True},
            ]}],
        }]
        self.assertTrue(focus.kitty_window_is_focused(data, "11"))
        self.assertFalse(focus.kitty_window_is_focused(data, "10"))

    def test_rejects_focused_window_in_background_os_window(self):
        data = [{
            "is_focused": False,
            "tabs": [{"windows": [{"id": 11, "is_focused": True}]}],
        }]
        self.assertFalse(focus.kitty_window_is_focused(data, "11"))

    def test_invalid_shapes_fail_open(self):
        self.assertFalse(focus.kitty_window_is_focused({}, "1"))
        self.assertFalse(focus.kitty_window_is_focused([None, {}], "1"))


class CommandLine(unittest.TestCase):
    def run_helper(self, command, data):
        return subprocess.run(
            [sys.executable, str(_MODULE_PATH), *command],
            input=data if isinstance(data, str) else json.dumps(data),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_wezterm_command_prints_id(self):
        result = self.run_helper(["wezterm-focused"], [{"focused_pane_id": 9}])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "9")

    def test_kitty_command_uses_exit_status(self):
        data = [{"is_focused": True, "tabs": [{"windows": [
            {"id": 3, "is_focused": True},
        ]}]}]
        self.assertEqual(self.run_helper(["kitty-focused", "3"], data).returncode, 0)
        self.assertEqual(self.run_helper(["kitty-focused", "4"], data).returncode, 1)

    def test_malformed_json_fails_open(self):
        result = self.run_helper(["wezterm-focused"], "not json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_unknown_command_is_usage_error(self):
        self.assertEqual(self.run_helper(["unknown"], []).returncode, 64)


if __name__ == "__main__":
    unittest.main()
