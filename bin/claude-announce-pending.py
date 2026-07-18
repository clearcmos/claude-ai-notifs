#!/usr/bin/env python3
"""Extract pending-input details from authoritative Claude Code hook payloads.

The conversation transcript is written asynchronously and can lag the live
tool dialog. Pending-input hooks therefore use their event-specific JSON:

  ask           PreToolUse for AskUserQuestion (tool_input.questions)
  permission    PermissionRequest (tool_name + tool_input)
  notification  Notification (title + message)

Prints nothing for malformed or mismatched input (exit 0: the caller treats
an empty task as an extraction failure and dings). Exits 3 with no output
when the event duplicates another hook's announcement for the same pause and
must stay fully silent. Stdlib only.
"""

import json
import sys


def string(value, limit):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def question_task(tool_input):
    """Describe one AskUserQuestion input without relying on the transcript."""
    if not isinstance(tool_input, dict):
        return ""
    questions = tool_input.get("questions")
    if not isinstance(questions, list):
        return ""
    parts = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        question = string(item.get("question"), 500)
        if not question:
            continue
        options = item.get("options")
        labels = []
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict):
                    label = string(option.get("label"), 100)
                    if label:
                        labels.append(label)
        if labels:
            question += " Options: " + ", ".join(labels)
        parts.append(question)
    if not parts:
        return ""
    # Framing must keep the direction of the ask (the user answers) without
    # naming the assistant; "a question needs the user's answer" made the
    # summarizer describe the user as the one waiting.
    return ("Waiting for the user to answer: "
            + " Also: ".join(parts))[:1500]


def permission_task(tool_name, tool_input):
    """Describe the tool approval dialog represented by PermissionRequest."""
    name = string(tool_name, 100)
    if not name:
        return ""
    task = "Permission is needed to use the " + name + " tool"
    if not isinstance(tool_input, dict):
        return task
    description = string(tool_input.get("description"), 300)
    command = string(tool_input.get("command"), 300)
    file_path = string(tool_input.get("file_path"), 300)
    if description:
        task += ". Purpose: " + description
    if command:
        task += ". Command: " + command
    elif file_path:
        task += ". File: " + file_path
    return task[:1500]


def notification_task(hook):
    """Describe a generic Notification using its documented message field."""
    if not isinstance(hook, dict):
        return ""
    message = string(hook.get("message"), 1200)
    if not message:
        return ""
    title = string(hook.get("title"), 200)
    if title and title.casefold() not in message.casefold():
        message = title + ". " + message
    return ("The user's attention is needed: " + message)[:1500]


def task_from_hook(hook, mode):
    if not isinstance(hook, dict):
        return ""
    if mode == "ask":
        if hook.get("hook_event_name") != "PreToolUse" \
                or hook.get("tool_name") != "AskUserQuestion":
            return ""
        return question_task(hook.get("tool_input"))
    if mode == "permission":
        if hook.get("hook_event_name") != "PermissionRequest":
            return ""
        # Approving AskUserQuestion is the same user pause the PreToolUse ask
        # hook announces with the actual question text; speaking this dialog
        # too made every question announce twice. None means suppress, which
        # is distinct from "" (extraction failure, which dings).
        if hook.get("tool_name") == "AskUserQuestion":
            return None
        return permission_task(hook.get("tool_name"), hook.get("tool_input"))
    if mode == "notification":
        if hook.get("hook_event_name") not in (None, "Notification"):
            return ""
        return notification_task(hook)
    return ""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "notification"
    try:
        hook = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    task = task_from_hook(hook, mode)
    if task is None:
        return 3
    if task:
        sys.stdout.write(task)
    return 0


if __name__ == "__main__":
    sys.exit(main())
