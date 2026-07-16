#!/usr/bin/env python3
"""Parse terminal focus-query JSON for claude-announce.

The terminal CLIs are the source of truth; this helper keeps their JSON parsing
pure, stdlib-only, and unit-testable. It reads one JSON document from stdin.
Invalid or unexpected data fails open: print nothing / return nonzero so the
caller speaks rather than silently dropping an announcement.
"""

import json
import os
import sys


def wezterm_focused_pane(clients):
    """Return the first reported focused pane id, or an empty string."""
    if not isinstance(clients, list):
        return ""
    for client in clients:
        if not isinstance(client, dict):
            continue
        pane_id = client.get("focused_pane_id")
        if pane_id is not None:
            return str(pane_id)
    return ""


def wezterm_pane_for_tty(panes, tty):
    """Return the pane id whose tty basename matches this session's tty."""
    if not isinstance(panes, list):
        return ""
    tty = os.path.basename(tty)
    for pane in panes:
        if not isinstance(pane, dict):
            continue
        if os.path.basename(pane.get("tty_name") or "") == tty:
            pane_id = pane.get("pane_id")
            return "" if pane_id is None else str(pane_id)
    return ""


def kitty_window_is_focused(os_windows, window_id):
    """True when window_id is focused inside the focused kitty OS window."""
    if not isinstance(os_windows, list):
        return False
    window_id = str(window_id)
    for os_window in os_windows:
        if not isinstance(os_window, dict) or not os_window.get("is_focused"):
            continue
        for tab in os_window.get("tabs") or []:
            if not isinstance(tab, dict):
                continue
            for window in tab.get("windows") or []:
                if (isinstance(window, dict)
                        and window.get("is_focused")
                        and str(window.get("id")) == window_id):
                    return True
    return False


def main(argv):
    try:
        data = json.load(sys.stdin)
    except (OSError, ValueError):
        return 1

    command = argv[1] if len(argv) > 1 else ""
    if command == "wezterm-focused" and len(argv) == 2:
        value = wezterm_focused_pane(data)
        if value:
            sys.stdout.write(value)
            return 0
        return 1
    if command == "wezterm-pane" and len(argv) == 3:
        value = wezterm_pane_for_tty(data, argv[2])
        if value:
            sys.stdout.write(value)
            return 0
        return 1
    if command == "kitty-focused" and len(argv) == 3:
        return 0 if kitty_window_is_focused(data, argv[2]) else 1
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
