#!/usr/bin/env python3
"""Summarizer-choice tests: the runtime honors $BASE/summarizer on macOS.

Runs the installed entrypoint with a shimmed `uname` reporting Darwin, so the
macOS selection logic is exercised on any CI platform. A fake Ollama server
counts hits: "ollama" recorded (or forced via CLAUDE_ANNOUNCE_SUMMARIZER) must
consult it, while the apple default must not, and both must exit 0 by falling
through the degradation chain (no Apple binary or claude CLI exists here).
"""

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import importlib.util

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL_PATH = ROOT / "bin" / "claude-announce-install.py"
SPEC = importlib.util.spec_from_file_location("installer", INSTALL_PATH)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def make_handler(hits):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            hits.append(self.path)
            response = {
                "status": "answered",
                "evidence": "answered the summarizer question",
                "topic": "summarizer question",
            }
            body = json.dumps({"response": json.dumps(response)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class SummarizerChoiceTests(unittest.TestCase):
    def run_darwin_stop(self, summarizer_file, env_extra, hits, port):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            home = root / "home"
            base = home / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(ROOT, base)
            venv_bin = base / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            (venv_bin / "python").symlink_to(sys.executable)
            fake_tts = current / "bin" / "claude-announce-tts.py"
            fake_tts.write_text(
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[2]).write_bytes(b'RIFF-fake-wave')\n"
            )
            fake_tts.chmod(0o700)

            (base / "ollama-host").write_text(
                "http://127.0.0.1:" + str(port) + "\n"
            )
            (base / "ollama-model").write_text("test-model\n")
            if summarizer_file is not None:
                (base / "summarizer").write_text(summarizer_file + "\n")

            commands = root / "commands"
            commands.mkdir()
            shims = {
                "uname": "#!/bin/sh\nprintf 'Darwin\\n'\n",
                "ps": "#!/bin/sh\nprintf 'ttys001\\n'\n",
                "osascript": "#!/bin/sh\nexit 0\n",
                "afplay": "#!/bin/sh\nexit 0\n",
                "say": "#!/bin/sh\nexit 0\n",
            }
            for name, script in shims.items():
                shim = commands / name
                shim.write_text(script)
                shim.chmod(shim.stat().st_mode | stat.S_IXUSR)

            env = {
                "HOME": str(home),
                "TERM_PROGRAM": "Apple_Terminal",
                # No claude CLI on this PATH: the haiku fallback must be
                # unavailable so the apple path degrades deterministically.
                "PATH": str(commands) + os.pathsep + "/usr/bin:/bin",
                "CLAUDE_ANNOUNCE_FORCE": "1",
                "TMPDIR": str(root),
            }
            env.update(env_extra)

            result = subprocess.run(
                [str(current / "bin" / "claude-announce"), "stop"],
                input=json.dumps({
                    "last_assistant_message": "I answered the summarizer question in detail."
                }),
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def serve(self):
        hits = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(hits))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, hits

    def test_recorded_ollama_choice_consults_ollama_on_darwin(self):
        server, thread, hits = self.serve()
        try:
            self.run_darwin_stop("ollama", {}, hits, server.server_port)
            self.assertTrue(hits, "recorded ollama choice never reached the Ollama API")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_darwin_default_stays_off_ollama(self):
        server, thread, hits = self.serve()
        try:
            self.run_darwin_stop(None, {}, hits, server.server_port)
            self.assertEqual(hits, [], "apple default must not consult Ollama")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_env_override_beats_missing_file(self):
        server, thread, hits = self.serve()
        try:
            self.run_darwin_stop(
                None, {"CLAUDE_ANNOUNCE_SUMMARIZER": "ollama"}, hits, server.server_port
            )
            self.assertTrue(hits, "CLAUDE_ANNOUNCE_SUMMARIZER=ollama was ignored")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
