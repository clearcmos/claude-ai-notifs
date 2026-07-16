#!/usr/bin/env python3
"""Transcript extraction for claude-announce.

Reads the Claude Code hook JSON on stdin, opens the session transcript
(JSONL) it points at, and prints the task text the summarizer should
compress into one spoken sentence:

  stop mode          last real user prompt plus Claude's final reply; prefers
                     the Stop hook's authoritative last_assistant_message and
                     falls back to transcript text for older Claude versions
  notification mode  what Claude is blocked on: an AskUserQuestion question
                     (with its options) or a tool permission prompt

Prints nothing and exits 0 when there is nothing to announce; the caller
then falls back to the plain ding. Stdlib only. This file is shared verbatim
with a sibling Linux setup; keep the copies identical so both machines
announce the same things.
"""

import json
import re
import sys


def text_of(content):
    """Join the text blocks of a message content field (string or array)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def load(path):
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def stop_task(entries, final_reply=""):
    # Last real user input: skip meta entries, tool results and harness noise.
    # Slash-command turns are stored as <command-name>/<command-args> tags, not
    # plain text; turn those into "Slash command: /name args" so command-only
    # sessions still get an announcement instead of the ding.
    prompts = []
    prompt_i = -1
    for i, e in enumerate(entries):
        if e.get("type") != "user" or e.get("isMeta"):
            continue
        t = text_of(e.get("message", {}).get("content"))
        if not t:
            continue
        m = re.search(r"<command-name>([^<]*)</command-name>", t)
        if m:
            a = re.search(r"<command-args>([^<]*)</command-args>", t)
            t = "Slash command: " + m.group(1) + (
                " " + a.group(1) if a and a.group(1) else "")
        if t.startswith("<") or t.startswith("Caveat:"):
            continue
        prompts.append(t)
        prompt_i = i
    prompt = (prompts[-1] if prompts else "")[:2000]

    # Claude's final user-facing reply: the last contiguous run of assistant
    # text entries, wherever it sits. A turn can end with tool calls (sending
    # a draft, saving a file), so "text after the last user entry" can be
    # empty even though Claude wrote a closing message just before them; fed
    # the request alone, the summarizer invents outcomes ("please fix the
    # docs sync" became "docs sync is fixed").
    # Search only this turn (after the last real user prompt) so a turn with
    # no assistant output never announces the previous turn's reply as fresh.
    last_text = -1
    for i, e in enumerate(entries):
        if i <= prompt_i:
            continue
        if (e.get("type") == "assistant"
                and text_of(e.get("message", {}).get("content"))):
            last_text = i
    transcript_reply = ""
    if last_text >= 0:
        start = last_text
        while start > 0 and entries[start - 1].get("type") == "assistant":
            start -= 1
        transcript_reply = " ".join(
            t for i in range(start, last_text + 1)
            for t in [text_of(entries[i].get("message", {}).get("content"))]
            if t)[:1800]

    # Claude Code documents last_assistant_message as the authoritative final
    # Stop reply: on some versions the transcript is not yet flushed when the
    # hook fires. Keep transcript_reply as a compatibility fallback.
    hook_reply = final_reply.strip() if isinstance(final_reply, str) else ""
    reply = (hook_reply or transcript_reply)[:1800]

    # In the transcript-fallback path, tool calls after its closing text were
    # the turn's real last actions; name the final one so the announcement can
    # be grounded in it. The authoritative hook reply is newer than any
    # partially flushed transcript, so never mislabel an older tool as having
    # happened after it. Same turn-scoping: never reach before the prompt.
    last_use = None
    if not hook_reply:
        for e in entries[max(last_text, prompt_i) + 1:]:
            if e.get("type") != "assistant":
                continue
            content = e.get("message", {}).get("content")
            if not isinstance(content, list):
                continue
            uses = [b for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_use"]
            if uses:
                last_use = uses[-1]

    if not prompt and not reply:
        return ""
    task = "User request:\n" + prompt[:600]
    if reply:
        task += "\n\nAssistant reply (start, may be truncated):\n" + reply
    else:
        task += ("\n\nAssistant reply: none recorded. Announce that Claude"
                 " worked on the request (mention its final action if one is"
                 " listed below); say neither that it succeeded nor that it"
                 " failed.")
    if last_use:
        inp = last_use.get("input") or {}
        detail = str(inp.get("description") or inp.get("command") or "")[:150]
        task += ("\n\nAfter that reply, Claude's final action was the "
                 + (last_use.get("name") or "?") + " tool"
                 + (": " + detail if detail else "") + ".")
    return task


def notification_task(entries):
    # The pending ask is the last assistant tool_use in the transcript: Claude
    # is blocked on it. AskUserQuestion carries the question text and options
    # in its input; any other tool means a permission prompt for that tool.
    last_use = None
    for e in entries:
        if e.get("type") != "assistant":
            continue
        content = e.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        uses = [b for b in content
                if isinstance(b, dict) and b.get("type") == "tool_use"]
        if uses:
            last_use = uses[-1]
    if not last_use:
        return ""
    inp = last_use.get("input") or {}
    if last_use.get("name") == "AskUserQuestion":
        parts = []
        for q in inp.get("questions") or []:
            opts = ", ".join(o.get("label", "") for o in q.get("options") or [])
            parts.append(q.get("question", "") + " Options: " + opts)
        task = "Claude is asking the user a question: " + " Also: ".join(parts)
    else:
        task = ("Claude is waiting for permission to use the "
                + (last_use.get("name") or "?") + " tool")
        if inp.get("description"):
            task += ". Purpose: " + str(inp["description"])
        if inp.get("command"):
            task += ". Command: " + str(inp["command"])[:200]
    return task[:1500]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "stop"
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return
    entries = []
    path = hook.get("transcript_path")
    if path:
        try:
            entries = load(path)
        except OSError:
            pass
    task = (notification_task(entries) if mode == "notification"
            else stop_task(entries, hook.get("last_assistant_message", "")))
    if task:
        sys.stdout.write(task)


if __name__ == "__main__":
    main()
