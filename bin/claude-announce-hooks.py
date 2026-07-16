#!/usr/bin/env python3
"""Wire or unwire the claude-announce hooks in a Claude Code settings.json.

Split out of setup.sh so the part that edits the user's real config is
unit-testable (tests/test_hooks.py) instead of living in a shell heredoc.
setup.sh invokes:

    claude-announce-hooks.py wire   <app-root> <settings-path>
    claude-announce-hooks.py unwire <settings-path>

Exit codes: 0 = wired / unwired / nothing to unwire; 2 = settings.json is not
valid JSON (the caller must then NOT claim success). Stdlib only.
"""

import json
import os
import shlex
import shutil
import sys
import tempfile
import time

NOTIFICATION_MATCHER = "permission_prompt|agent_needs_input|elicitation_dialog"


def announce_path(app_root):
    return os.path.join(app_root, "bin", "claude-announce")


def is_ours(entry, announce=None):
    """True if this hook entry runs our announcer (current exec form or the
    legacy shell form) or the legacy notify-unfocused.sh it superseded.

    Inspects only each hook's command field, never the whole entry, so an
    unrelated hook that merely mentions the name in a matcher/description is
    never matched. An exact `announce` path matches when known; the command
    basename also matches, so an install whose repo has since moved is still
    recognized for cleanup.
    """
    for h in entry.get("hooks", []) or []:
        cmd = h.get("command", "") or ""
        if not cmd:
            continue
        if announce and (cmd == announce or cmd.startswith(announce + " ")):
            return True
        if "notify-unfocused.sh" in cmd:
            return True
        # The executable path: in exec form (an "args" array is present) the
        # command IS the opaque path - a path with spaces stays intact, so use
        # it directly (splitting on spaces here was the uninstall-misses bug).
        # In shell form the path is the first shell token of the command string.
        if "args" in h:
            exe = cmd
        else:
            try:
                exe = shlex.split(cmd)[0]
            except (ValueError, IndexError):
                parts = cmd.split()
                exe = parts[0] if parts else ""
        if os.path.basename(exe) == "claude-announce":
            return True
    return False


def _hook(announce, arg):
    # Exec form: no shell tokenization (spaces in the repo path are safe), and
    # async so the several-second announcement never blocks the session.
    return {"type": "command", "command": announce, "args": [arg], "async": True}


def wire(settings, announce):
    """Add (or refresh) our Stop + Notification hooks, dropping any prior form
    first so re-runs stay idempotent. Mutates and returns settings."""
    hooks = settings.setdefault("hooks", {})
    hooks["Stop"] = [e for e in hooks.get("Stop", []) if not is_ours(e, announce)]
    hooks["Stop"].append({"hooks": [_hook(announce, "stop")]})
    hooks["Notification"] = [
        e for e in hooks.get("Notification", []) if not is_ours(e, announce)
    ]
    hooks["Notification"].append(
        {"matcher": NOTIFICATION_MATCHER, "hooks": [_hook(announce, "notification")]}
    )
    return settings


def unwire(settings):
    """Remove our hooks (any form) from Stop + Notification, dropping an event
    key entirely once it is empty. Returns True if anything changed."""
    hooks = settings.get("hooks", {})
    changed = False
    for event in ("Stop", "Notification"):
        entries = hooks.get(event)
        if not entries:
            continue
        kept = [e for e in entries if not is_ours(e)]
        if len(kept) != len(entries):
            changed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    return changed


def write_atomic(path, settings):
    """Write via a temp sibling + os.replace so a crash mid-write can never
    truncate settings.json; carry the original file mode over. mkstemp makes
    the sibling unpredictable and 0600 even outside setup.sh's private umask."""
    directory = os.path.dirname(path) or "."
    prefix = os.path.basename(path) + ".tmp."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=prefix, text=True)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        try:
            os.chmod(tmp, os.stat(path).st_mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup(path):
    dest = path + ".bak." + time.strftime("%Y%m%d-%H%M%S") + "." + str(os.getpid())
    shutil.copy2(path, dest)
    return dest


def main(argv):
    if len(argv) >= 4 and argv[1] == "wire":
        app_root, path = argv[2], argv[3]
        announce = announce_path(app_root)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    settings = json.load(f)
            except ValueError as e:
                sys.exit("    " + path + " is not valid JSON (" + str(e) + "); fix it and re-run")
            print("    backup: " + _backup(path))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            settings = {}
        wire(settings, announce)
        write_atomic(path, settings)
        print("    hooks.Stop and hooks.Notification now run " + announce + " (async)")
        return 0

    if len(argv) >= 3 and argv[1] == "unwire":
        path = argv[2]
        try:
            with open(path) as f:
                settings = json.load(f)
        except ValueError as e:
            sys.stderr.write("    " + path + " is not valid JSON (" + str(e) + ")\n")
            return 2
        if unwire(settings):
            dest = _backup(path)
            write_atomic(path, settings)
            print("    removed claude-announce hooks (backup: " + dest + ")")
        else:
            print("    no claude-announce hooks found in " + path)
        return 0

    sys.stderr.write(
        "usage: claude-announce-hooks.py wire <app-root> <settings> | unwire <settings>\n"
    )
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
