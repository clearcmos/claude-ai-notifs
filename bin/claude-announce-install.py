#!/usr/bin/env python3
"""Install the repo-backed runtime as an atomic, self-contained release.

Usage: claude-announce-install.py <repo> <base>

Copies every script needed after installation into:
  <base>/runtime/releases/<unique>/bin
then atomically points <base>/runtime/current at that complete release. The
hook always targets the stable current/bin/claude-announce path. Stdlib only.
"""

import os
import pathlib
import secrets
import shutil
import sys
import time


RUNTIME_FILES = (
    "claude-announce",
    "claude-announce-ding.py",
    "claude-announce-extract.py",
    "claude-announce-foot",
    "claude-announce-foot-config.py",
    "claude-announce-focus.py",
    "claude-announce-hooks.py",
    "claude-announce-ollama.py",
    "claude-announce-pending.py",
    "claude-announce-render.py",
    "claude-announce-tts.py",
    "claude-announce-uninstall",
)


def install_runtime(repo, base):
    repo = pathlib.Path(repo).resolve()
    base = pathlib.Path(base).resolve()
    runtime = base / "runtime"
    releases = runtime / "releases"

    sources = [repo / "bin" / name for name in RUNTIME_FILES]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing runtime file(s): " + ", ".join(missing))

    releases.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime, 0o700)
    os.chmod(releases, 0o700)

    release_name = (
        time.strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid()) + "-"
        + secrets.token_hex(4)
    )
    release = releases / release_name
    release_bin = release / "bin"
    temporary_link = runtime / (".current." + release_name)

    try:
        release_bin.mkdir(parents=True, mode=0o700)
        os.chmod(release, 0o700)
        os.chmod(release_bin, 0o700)
        for source in sources:
            destination = release_bin / source.name
            shutil.copyfile(source, destination)
            os.chmod(destination, 0o700)

        # Relative target keeps the installation relocatable as one BASE tree.
        os.symlink(os.path.join("releases", release_name), temporary_link)
        os.replace(temporary_link, runtime / "current")
    except BaseException:
        try:
            temporary_link.unlink()
        except OSError:
            pass
        shutil.rmtree(release, ignore_errors=True)
        raise

    return runtime / "current"


def main(argv):
    if len(argv) != 3:
        sys.stderr.write("usage: claude-announce-install.py <repo> <base>\n")
        return 64
    try:
        current = install_runtime(argv[1], argv[2])
    except (OSError, ValueError) as error:
        sys.stderr.write("runtime installation failed: " + str(error) + "\n")
        return 1
    print(current)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
