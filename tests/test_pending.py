#!/usr/bin/env python3
"""Tests for authoritative pending-input hook payload extraction."""

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "bin"
    / "claude-announce-pending.py"
)
SPEC = importlib.util.spec_from_file_location("claude_announce_pending", MODULE_PATH)
pending = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pending)


class AskUserQuestion(unittest.TestCase):
    def test_extracts_question_and_choices_from_pretooluse(self):
        hook = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [{
                    "header": "Scope",
                    "question": "What do you want to sanitize, and what's the goal?",
                    "options": [
                        {"label": "Extract one module", "description": "Small"},
                        {"label": "Sanitize a subset", "description": "Bounded"},
                        {"label": "Whole-repo public copy", "description": "Risky"},
                    ],
                    "multiSelect": False,
                }]
            },
        }
        task = pending.task_from_hook(hook, "ask")
        self.assertIn("What do you want to sanitize", task)
        self.assertIn("Extract one module", task)
        self.assertIn("Sanitize a subset", task)
        self.assertIn("Whole-repo public copy", task)

    def test_rejects_mismatched_tool_event(self):
        hook = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"questions": [{"question": "Wrong event"}]},
        }
        self.assertEqual(pending.task_from_hook(hook, "ask"), "")

    def test_cli_does_not_need_a_flushed_transcript(self):
        hook = {
            "hook_event_name": "PreToolUse",
            "transcript_path": "/does/not/exist.jsonl",
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [{
                    "question": "Which database?",
                    "options": [{"label": "Postgres"}, {"label": "SQLite"}],
                }]
            },
        }
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "ask"],
            input=json.dumps(hook),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Which database?", result.stdout)
        self.assertIn("Postgres, SQLite", result.stdout)


class PermissionRequest(unittest.TestCase):
    def test_extracts_tool_and_command(self):
        hook = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {
                "description": "Clean the generated directory",
                "command": "rm -rf build",
            },
        }
        task = pending.task_from_hook(hook, "permission")
        self.assertIn("Permission is needed to use the Bash tool", task)
        self.assertIn("Clean the generated directory", task)
        self.assertIn("rm -rf build", task)

    def test_extracts_file_path_when_there_is_no_command(self):
        hook = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/report.md"},
        }
        self.assertIn(
            "/tmp/report.md", pending.task_from_hook(hook, "permission")
        )

    def test_ask_user_question_approval_is_suppressed(self):
        # The PreToolUse ask hook announces this same pause with the actual
        # question, so its approval dialog must not speak a second sentence.
        hook = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which repo?"}]},
        }
        self.assertIsNone(pending.task_from_hook(hook, "permission"))

    def test_cli_signals_suppression_with_exit_code_3(self):
        hook = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which repo?"}]},
        }
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "permission"],
            input=json.dumps(hook),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_other_tool_approvals_still_announce_with_exit_zero(self):
        hook = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        }
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "permission"],
            input=json.dumps(hook),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Permission is needed to use the Bash tool", result.stdout)


class Notification(unittest.TestCase):
    def test_uses_documented_message_without_transcript(self):
        hook = {
            "hook_event_name": "Notification",
            "notification_type": "elicitation_dialog",
            "title": "Input needed",
            "message": "The deployment server needs a region.",
        }
        task = pending.task_from_hook(hook, "notification")
        self.assertIn("Input needed", task)
        self.assertIn("deployment server needs a region", task)

    def test_empty_message_returns_empty(self):
        self.assertEqual(
            pending.task_from_hook(
                {"hook_event_name": "Notification", "message": ""},
                "notification",
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
