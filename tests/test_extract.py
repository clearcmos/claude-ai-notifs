#!/usr/bin/env python3
"""Unit tests for bin/claude-announce-extract.py.

The extract script holds most of the tool's behavioral risk: turn scoping, the
anti-hallucination "none recorded" path, slash-command handling, and the
notification (blocked-on) logic. It is stdlib-only and its two entry points
(stop_task, notification_task) are pure functions of a parsed transcript, so we
exercise them directly with synthetic entries. No macOS, no audio, no network.

The script filename has hyphens, so it is loaded by path rather than imported;
this keeps the file itself untouched (it is shared verbatim with the sibling
Linux setup). Run: python -m unittest discover -s tests
"""

import importlib.util
import pathlib
import unittest

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "bin"
    / "claude-announce-extract.py"
)
_spec = importlib.util.spec_from_file_location("claude_announce_extract", _MODULE_PATH)
extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract)


# --- transcript entry builders (mirror the Claude Code JSONL shapes) ---------

def user(text, meta=False):
    e = {"type": "user", "message": {"content": text}}
    if meta:
        e["isMeta"] = True
    return e


def assistant_text(text):
    return {"type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]}}


def assistant_tool(name, **inp):
    return {"type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def assistant_ask(*questions):
    return {"type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion",
                                     "input": {"questions": list(questions)}}]}}


class TextOf(unittest.TestCase):
    def test_string_passthrough(self):
        self.assertEqual(extract.text_of("hello"), "hello")

    def test_joins_text_blocks(self):
        content = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        self.assertEqual(extract.text_of(content), "a\nb")

    def test_ignores_non_text_blocks(self):
        content = [{"type": "text", "text": "keep"},
                   {"type": "tool_use", "name": "Bash", "input": {}}]
        self.assertEqual(extract.text_of(content), "keep")

    def test_non_str_non_list_is_empty(self):
        self.assertEqual(extract.text_of(None), "")
        self.assertEqual(extract.text_of(42), "")


class StopTask(unittest.TestCase):
    def test_prompt_and_reply(self):
        task = extract.stop_task([
            user("Fix the parser bug"),
            assistant_text("Fixed the off-by-one in the parser."),
        ])
        self.assertIn("User request:", task)
        self.assertIn("Fix the parser bug", task)
        self.assertIn("Assistant reply (start, may be truncated):", task)
        self.assertIn("Fixed the off-by-one in the parser.", task)
        self.assertNotIn("none recorded", task)

    def test_turn_ending_in_tool_use_keeps_closing_reply(self):
        # The closing text sits before the final tool calls; it must still be
        # captured (this is the docs-sync regression the code guards against).
        task = extract.stop_task([
            user("Save the file"),
            assistant_text("Saved and verified."),
            assistant_tool("Bash", command="ls"),
        ])
        self.assertIn("Saved and verified.", task)
        self.assertIn("final action was the Bash tool", task)
        self.assertIn(": ls", task)
        self.assertNotIn("none recorded", task)

    def test_no_reply_text_uses_none_recorded(self):
        # Turn with no assistant prose at all: must NOT invent an outcome from
        # the request, and must name the final tool action instead.
        task = extract.stop_task([
            user("Deploy the service"),
            assistant_tool("Bash", description="deploy to prod"),
        ])
        self.assertIn("Assistant reply: none recorded", task)
        self.assertIn("say neither that it succeeded nor that it failed", task)
        self.assertIn("final action was the Bash tool", task)
        self.assertIn("deploy to prod", task)

    def test_turn_scoping_ignores_previous_turn_reply(self):
        # A new turn with no reply must not announce the PRIOR turn's reply as
        # if it were fresh.
        task = extract.stop_task([
            user("first task"),
            assistant_text("Did the first thing."),
            user("second task"),
            assistant_tool("Write", description="write a file"),
        ])
        self.assertIn("second task", task)
        self.assertNotIn("Did the first thing.", task)
        self.assertIn("none recorded", task)

    def test_slash_command_rewritten(self):
        cmd = "<command-name>/deploy</command-name>\n<command-args>prod now</command-args>"
        task = extract.stop_task([user(cmd)])
        self.assertIn("Slash command: /deploy prod now", task)

    def test_meta_caveat_and_tag_prompts_skipped(self):
        task = extract.stop_task([
            user("real prompt"),
            user("Caveat: this is harness noise"),
            user("<local-command-stdout>noise</local-command-stdout>"),
            user("ignored meta", meta=True),
        ])
        self.assertIn("real prompt", task)
        self.assertNotIn("Caveat:", task)
        self.assertNotIn("harness noise", task)
        self.assertNotIn("ignored meta", task)

    def test_empty_transcript_returns_empty(self):
        self.assertEqual(extract.stop_task([]), "")

    def test_tool_only_no_user_returns_empty(self):
        self.assertEqual(extract.stop_task([assistant_tool("Bash", command="x")]), "")


class NotificationTask(unittest.TestCase):
    def test_ask_user_question(self):
        task = extract.notification_task([
            assistant_ask({"question": "Which database?",
                           "options": [{"label": "Postgres"}, {"label": "MySQL"}]}),
        ])
        self.assertIn("Claude is asking the user a question:", task)
        self.assertIn("Which database?", task)
        self.assertIn("Options: Postgres, MySQL", task)

    def test_permission_prompt_with_command_and_purpose(self):
        task = extract.notification_task([
            assistant_tool("Bash", command="rm -rf build", description="clean build dir"),
        ])
        self.assertIn("waiting for permission to use the Bash tool", task)
        self.assertIn("Purpose: clean build dir", task)
        self.assertIn("Command: rm -rf build", task)

    def test_last_tool_use_wins(self):
        task = extract.notification_task([
            assistant_tool("Read", command="cat a"),
            assistant_tool("Edit", description="edit b"),
        ])
        self.assertIn("Edit tool", task)
        self.assertNotIn("Read tool", task)

    def test_no_tool_use_returns_empty(self):
        task = extract.notification_task([assistant_text("just talking"), user("hi")])
        self.assertEqual(task, "")


if __name__ == "__main__":
    unittest.main()
