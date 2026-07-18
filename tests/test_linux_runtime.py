#!/usr/bin/env python3
"""End-to-end Linux hook test with fake Ollama, tty, and Kokoro."""

import importlib.util
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


ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL_PATH = ROOT / "bin" / "claude-announce-install.py"
SPEC = importlib.util.spec_from_file_location("installer", INSTALL_PATH)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class OllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path != "/api/generate":
            self.send_error(404)
            return
        if request.get("format"):
            response = {
                "status": "answered",
                "evidence": "answered the foot question",
                "topic": "foot question",
            }
        else:
            response = "Claude needs your input."
        body = json.dumps({"response": json.dumps(response) if isinstance(response, dict) else response}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(os.uname().sysname == "Linux", "Linux runtime test")
class LinuxRuntimeTests(unittest.TestCase):
    def test_grounded_stop_queues_wav_and_osc_for_foot(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
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
                    "http://127.0.0.1:" + str(server.server_port) + "\n"
                )
                (base / "ollama-model").write_text("llama3.2:3b\n")
                (base / "enabled-terminals").write_text("foot\n")

                commands = root / "commands"
                commands.mkdir()
                ps = commands / "ps"
                ps.write_text("#!/bin/sh\nprintf 'pts/9\\n'\n")
                ps.chmod(ps.stat().st_mode | stat.S_IXUSR)

                runtime_dir = root / "runtime"
                runtime_dir.mkdir()
                tty = root / "tty"
                env = os.environ.copy()
                env.update({
                    "HOME": str(home),
                    "TERM": "foot",
                    "TERM_PROGRAM": "",
                    "XDG_RUNTIME_DIR": str(runtime_dir),
                    "CLAUDE_ANNOUNCE_TTY_FILE": str(tty),
                    "PATH": str(commands) + os.pathsep + env["PATH"],
                })
                for name in (
                    "OLLAMA_HOST",
                    "CLAUDE_ANNOUNCE_OLLAMA_HOST",
                    "CLAUDE_ANNOUNCE_INNER",
                    "CLAUDE_ANNOUNCE_FORCE",
                ):
                    env.pop(name, None)

                result = subprocess.run(
                    [str(current / "bin" / "claude-announce"), "stop"],
                    input=json.dumps({
                        "last_assistant_message": "I answered the foot question clearly."
                    }),
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = tty.read_bytes()
                self.assertIn(b"\x1b]777;notify;claude-ai-notifs;ready-", payload)
                token = payload.split(b";")[-1].removesuffix(b"\x1b\\").decode()
                item = runtime_dir / "claude-ai-notifs" / token
                self.assertEqual(
                    (item / "summary.txt").read_text(),
                    "Explained foot question.",
                )
                self.assertTrue((item / "announcement.wav").read_bytes().startswith(b"RIFF"))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_ask_user_question_uses_pretool_input_before_transcript_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            home = root / "home"
            base = home / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(ROOT, base)
            venv_bin = base / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            (venv_bin / "python").symlink_to(sys.executable)

            request_log = root / "ollama-prompt"
            fake_ollama = current / "bin" / "claude-announce-ollama.py"
            fake_ollama.write_text(
                "import os, pathlib, sys\n"
                "pathlib.Path(os.environ['REQUEST_LOG']).write_text(sys.stdin.read())\n"
                "print('Claude is asking what you want to sanitize.')\n"
            )
            fake_ollama.chmod(0o700)
            fake_tts = current / "bin" / "claude-announce-tts.py"
            fake_tts.write_text(
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[2]).write_bytes(b'RIFF-fake-wave')\n"
            )
            fake_tts.chmod(0o700)

            (base / "ollama-host").write_text("http://127.0.0.1:11434\n")
            (base / "ollama-model").write_text("llama3.2:3b\n")
            (base / "enabled-terminals").write_text("foot\n")

            commands = root / "commands"
            commands.mkdir()
            ps = commands / "ps"
            ps.write_text("#!/bin/sh\nprintf 'pts/9\\n'\n")
            ps.chmod(ps.stat().st_mode | stat.S_IXUSR)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            tty = root / "tty"
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "TERM": "foot",
                "TERM_PROGRAM": "",
                "XDG_RUNTIME_DIR": str(runtime_dir),
                "CLAUDE_ANNOUNCE_TTY_FILE": str(tty),
                "REQUEST_LOG": str(request_log),
                "PATH": str(commands) + os.pathsep + env["PATH"],
            })
            for name in (
                "OLLAMA_HOST",
                "CLAUDE_ANNOUNCE_OLLAMA_HOST",
                "CLAUDE_ANNOUNCE_INNER",
                "CLAUDE_ANNOUNCE_FORCE",
            ):
                env.pop(name, None)

            result = subprocess.run(
                [str(current / "bin" / "claude-announce"), "ask"],
                input=json.dumps({
                    "hook_event_name": "PreToolUse",
                    "tool_name": "AskUserQuestion",
                    "transcript_path": str(root / "not-yet-flushed.jsonl"),
                    "tool_input": {
                        "questions": [{
                            "question": "What do you want to sanitize?",
                            "options": [
                                {"label": "One module"},
                                {"label": "A subset"},
                            ],
                        }]
                    },
                }),
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            prompt = request_log.read_text()
            self.assertIn("What do you want to sanitize?", prompt)
            self.assertIn("One module, A subset", prompt)
            payload = tty.read_bytes()
            token = payload.split(b";")[-1].removesuffix(b"\x1b\\").decode()
            item = runtime_dir / "claude-ai-notifs" / token
            # The fake model deliberately still names Claude; the summary that
            # reaches playback proves the hook's strip_actor removed it.
            self.assertEqual(
                (item / "summary.txt").read_text(),
                "asking what you want to sanitize.",
            )
            self.assertTrue((item / "announcement.wav").is_file())

    def test_ask_user_question_approval_is_fully_silent(self):
        # PermissionRequest for AskUserQuestion duplicates the ask hook's
        # announcement of the same pause; the hook must exit without dinging,
        # summarizing, or writing any OSC 777 payload to the session tty.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            home = root / "home"
            base = home / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(ROOT, base)
            venv_bin = base / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            (venv_bin / "python").symlink_to(sys.executable)

            request_log = root / "ollama-prompt"
            fake_ollama = current / "bin" / "claude-announce-ollama.py"
            fake_ollama.write_text(
                "import os, pathlib, sys\n"
                "pathlib.Path(os.environ['REQUEST_LOG']).write_text(sys.stdin.read())\n"
                "print('this event must never reach a summarizer')\n"
            )
            fake_ollama.chmod(0o700)
            fake_tts = current / "bin" / "claude-announce-tts.py"
            fake_tts.write_text(
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[2]).write_bytes(b'RIFF-fake-wave')\n"
            )
            fake_tts.chmod(0o700)

            (base / "ollama-host").write_text("http://127.0.0.1:11434\n")
            (base / "ollama-model").write_text("llama3.2:3b\n")
            (base / "enabled-terminals").write_text("foot\n")

            commands = root / "commands"
            commands.mkdir()
            ps = commands / "ps"
            ps.write_text("#!/bin/sh\nprintf 'pts/9\\n'\n")
            ps.chmod(ps.stat().st_mode | stat.S_IXUSR)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            tty = root / "tty"
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "TERM": "foot",
                "TERM_PROGRAM": "",
                "XDG_RUNTIME_DIR": str(runtime_dir),
                "CLAUDE_ANNOUNCE_TTY_FILE": str(tty),
                "REQUEST_LOG": str(request_log),
                "PATH": str(commands) + os.pathsep + env["PATH"],
            })
            for name in (
                "OLLAMA_HOST",
                "CLAUDE_ANNOUNCE_OLLAMA_HOST",
                "CLAUDE_ANNOUNCE_INNER",
                "CLAUDE_ANNOUNCE_FORCE",
            ):
                env.pop(name, None)

            result = subprocess.run(
                [str(current / "bin" / "claude-announce"), "permission"],
                input=json.dumps({
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "AskUserQuestion",
                    "tool_input": {
                        "questions": [{"question": "Which repo?"}]
                    },
                }),
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(tty.exists())
            self.assertFalse(request_log.exists())
            self.assertFalse((runtime_dir / "claude-ai-notifs").exists())


if __name__ == "__main__":
    unittest.main()
