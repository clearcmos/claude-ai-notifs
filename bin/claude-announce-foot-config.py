#!/usr/bin/env python3
"""Safely add or remove the foot OSC 777 dispatcher configuration."""

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time


BEGIN = "# claude-ai-notifs: begin managed foot notification adapter"
END = "# claude-ai-notifs: end managed foot notification adapter"


class ConfigConflict(RuntimeError):
    pass


def write_target(path):
    """Preserve a user-managed foot.ini symlink and edit its target atomically."""
    path = pathlib.Path(path)
    return path.resolve(strict=False) if path.is_symlink() else path


def quote_foot_arg(value):
    if "\n" in value or "\r" in value:
        raise ValueError("foot dispatcher path contains a newline")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dispatcher_command(executable):
    fields = (
        "${title}",
        "${body}",
        "${app-id}",
        "${icon}",
        "${category}",
        "${urgency}",
        "${expire-time}",
        "${replace-id}",
        "${muted}",
        "${sound-name}",
        "${action-argument}",
    )
    return quote_foot_arg(str(executable)) + " dispatch " + " ".join(fields)


def managed_block(executable):
    return "\n".join((
        BEGIN,
        "[desktop-notifications]",
        "command=" + dispatcher_command(executable),
        "command-action-argument=--action ${action-name}=${action-label}",
        "inhibit-when-focused=yes",
        END,
    ))


def split_managed(text):
    clean = []
    blocks = []
    current = []
    inside = False
    for line in text.splitlines(keepends=True):
        marker = line.rstrip("\r\n")
        if marker == BEGIN:
            if inside:
                raise ValueError("nested claude-ai-notifs foot configuration block")
            inside = True
            current = [line]
        elif marker == END:
            if not inside:
                raise ValueError("orphaned claude-ai-notifs foot configuration marker")
            current.append(line)
            blocks.append("".join(current))
            current = []
            inside = False
        elif inside:
            current.append(line)
        else:
            clean.append(line)
    if inside:
        raise ValueError("unterminated claude-ai-notifs foot configuration block")
    return "".join(clean), blocks


def explicit_desktop_settings(text):
    section = ""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "desktop-notifications" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        if key in ("command", "command-action-argument", "inhibit-when-focused"):
            values[key] = value.strip()
    return values


def inspect_config(path):
    path = pathlib.Path(path)
    text = path.read_text() if path.exists() else ""
    clean, blocks = split_managed(text)
    values = explicit_desktop_settings(clean)
    inhibit = values.get("inhibit-when-focused", "").lower()
    return {
        "exists": path.exists(),
        "managed": bool(blocks),
        "custom_command": "command" in values,
        "inhibit_disabled": inhibit in ("no", "false", "off", "0"),
        "command": values.get("command", ""),
    }


def backup(path):
    destination = str(path) + ".bak." + time.strftime("%Y%m%d-%H%M%S")
    destination += "." + str(os.getpid())
    shutil.copy2(path, destination)
    return destination


def validate_with_foot(temporary, foot_binary):
    if not foot_binary:
        return
    result = subprocess.run(
        [foot_binary, "--check-config", "--config", str(temporary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError("foot rejected the generated configuration: " + detail)


def write_atomic(path, text, foot_binary=None):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".tmp.", text=True
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        else:
            os.chmod(temporary, 0o600)
        validate_with_foot(temporary, foot_binary)
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def configure(path, executable, force=False, foot_binary=None):
    requested = pathlib.Path(path)
    path = write_target(requested)
    text = path.read_text() if path.exists() else ""
    clean, blocks = split_managed(text)
    values = explicit_desktop_settings(clean)
    inhibit = values.get("inhibit-when-focused", "").lower()
    conflicts = []
    # A pre-existing managed block records that setup already obtained consent
    # to overlay these values. Re-runs must remain non-interactive and move the
    # block back to the end if the user added more foot settings after it.
    if not blocks:
        if "command" in values:
            conflicts.append("an explicit desktop-notifications.command")
        if "command-action-argument" in values:
            conflicts.append("an explicit desktop-notifications.command-action-argument")
        if inhibit in ("no", "false", "off", "0"):
            conflicts.append("inhibit-when-focused disabled")
    if conflicts and not force:
        raise ConfigConflict(" and ".join(conflicts))

    # Keep every pre-existing byte outside our marked block. In particular, do
    # not add an unmarked blank line that uninstall could not distinguish from
    # a line the user intentionally added.
    prefix = clean
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += "\n"
    updated = prefix + managed_block(executable) + "\n"
    if updated == text:
        return None
    # For a dotfiles symlink, keep the safety backup beside the user-facing
    # link rather than creating an untracked backup inside the repository.
    destination = backup(requested) if requested.exists() else None
    write_atomic(path, updated, foot_binary)
    return destination


def restore(path, foot_binary=None):
    requested = pathlib.Path(path)
    path = write_target(requested)
    if not path.exists():
        return False
    text = path.read_text()
    clean, blocks = split_managed(text)
    if not blocks:
        return False
    backup(requested)
    write_atomic(path, clean, foot_binary)
    return True


def parser():
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("config")

    configure_parser = subparsers.add_parser("configure")
    configure_parser.add_argument("config")
    configure_parser.add_argument("dispatcher")
    configure_parser.add_argument("--force", action="store_true")
    configure_parser.add_argument("--foot-binary")

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("config")
    restore_parser.add_argument("--foot-binary")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            print(json.dumps(inspect_config(args.config), sort_keys=True))
        elif args.command == "configure":
            destination = configure(
                args.config,
                args.dispatcher,
                force=args.force,
                foot_binary=args.foot_binary,
            )
            if destination:
                print("    backup: " + destination)
            print("    foot OSC 777 adapter configured in " + args.config)
        elif args.command == "restore":
            if restore(args.config, args.foot_binary):
                print("    removed claude-ai-notifs foot configuration from " + args.config)
            else:
                print("    no claude-ai-notifs foot configuration found in " + args.config)
    except ConfigConflict as error:
        print("foot configuration conflict: " + str(error), file=sys.stderr)
        return 3
    except (OSError, ValueError) as error:
        print("foot configuration failed: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
