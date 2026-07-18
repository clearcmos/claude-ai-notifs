#!/usr/bin/env python3

import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
FOOT = ROOT / "bin" / "claude-announce-foot"


def executable(path, content):
    path.write_text("#!/bin/sh\n" + content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@unittest.skipUnless(os.uname().sysname == "Linux", "Linux foot delivery test")
class FootDeliveryTests(unittest.TestCase):
    def environment(self, root):
        base = root / "base"
        spool = root / "spool"
        commands = root / "commands"
        commands.mkdir()
        log = root / "calls"
        executable(commands / "paplay", 'printf "paplay:%s\\n" "$*" >> "$CALL_LOG"\n')
        executable(commands / "pactl", "exit 1\n")
        executable(
            commands / "notify-send",
            'printf "notify:%s\\n" "$*" >> "$CALL_LOG"\nprintf "42\\n"\n',
        )
        env = os.environ.copy()
        env.update({
            "CLAUDE_ANNOUNCE_BASE": str(base),
            "CLAUDE_ANNOUNCE_SPOOL": str(spool),
            "CALL_LOG": str(log),
            "PATH": str(commands) + os.pathsep + env["PATH"],
        })
        return env, spool, log

    def test_enqueue_and_dispatch_tokenized_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, spool, log = self.environment(root)
            base = pathlib.Path(env["CLAUDE_ANNOUNCE_BASE"])
            base.mkdir(parents=True)
            (base / "debug").touch()
            tty = root / "tty"
            wav = root / "source.wav"
            wav.write_bytes(b"RIFF-test")
            env["CLAUDE_ANNOUNCE_TTY_FILE"] = str(tty)

            queued = subprocess.run(
                ["bash", str(FOOT), "enqueue", "stop", "Claude answered foot.", str(wav), "pts/7"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(queued.returncode, 0, queued.stderr)
            payload = tty.read_bytes()
            self.assertTrue(payload.startswith(b"\x1b]777;notify;claude-ai-notifs;ready-"))
            token = payload.split(b";")[-1].removesuffix(b"\x1b\\").decode()
            self.assertTrue((spool / token / "announcement.wav").is_file())

            dispatched = subprocess.run(
                [
                    "bash", str(FOOT), "dispatch", "claude-ai-notifs", token,
                    "foot", "", "", "normal", "-1", "0", "false", "", 
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
            self.assertIn("paplay:", log.read_text())
            self.assertIn("played " + token + " successfully",
                          (base / "debug.log").read_text())
            self.assertFalse((spool / token).exists())

    def test_failed_fallback_ding_is_logged_and_becomes_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, spool, log = self.environment(root)
            base = pathlib.Path(env["CLAUDE_ANNOUNCE_BASE"])
            base.mkdir(parents=True)
            (base / "debug").touch()
            (base / "ding.wav").write_bytes(b"RIFF")
            executable(root / "commands" / "paplay", "exit 7\n")
            executable(root / "commands" / "canberra-gtk-play", "exit 8\n")
            item = spool / "ready-DING"
            item.mkdir(parents=True)
            (item / "summary.txt").write_text("Claude needs input")

            result = subprocess.run(
                [
                    "bash", str(FOOT), "dispatch", "claude-ai-notifs", "ready-DING",
                    "foot", "", "", "normal", "-1", "0", "false", "",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("notify:", log.read_text())
            self.assertIn(
                "fallback ding failed for ready-DING; delivered a notification",
                (base / "debug.log").read_text(),
            )

    def test_non_project_notifications_are_forwarded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, _spool, log = self.environment(root)
            result = subprocess.run(
                [
                    "bash", str(FOOT), "dispatch", "Build finished", "Everything passed",
                    "foot", "icon.png", "build", "normal", "5000", "0", "false", "",
                    "--action", "default=Open",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            call = log.read_text()
            self.assertIn("notify:", call)
            self.assertIn("Build finished Everything passed", call)
            self.assertEqual(result.stdout, "42\n")

    def test_concurrent_dispatchers_serialize_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, spool, log = self.environment(root)
            executable(
                root / "commands" / "paplay",
                'printf "start:%s\\n" "$1" >> "$CALL_LOG"\n'
                'sleep 0.2\n'
                'printf "end:%s\\n" "$1" >> "$CALL_LOG"\n',
            )
            tokens = ("ready-A1", "ready-B2", "ready-C3")
            for token in tokens:
                item = spool / token
                item.mkdir(parents=True)
                (item / "summary.txt").write_text(token)
                (item / "announcement.wav").write_bytes(b"RIFF")

            processes = [
                subprocess.Popen(
                    [
                        "bash", str(FOOT), "dispatch", "claude-ai-notifs", token,
                        "foot", "", "", "normal", "-1", "0", "false", "",
                    ],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for token in tokens
            ]
            for process in processes:
                _stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
            phases = [line.split(":", 1)[0] for line in log.read_text().splitlines()]
            self.assertEqual(phases, ["start", "end", "start", "end", "start", "end"])

    def test_microphone_capture_uses_silent_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, spool, log = self.environment(root)
            executable(
                root / "commands" / "pactl",
                'if [ "$*" = "list short sources" ]; then printf "1\\tmic\\n2\\tspeakers.monitor\\n"; '
                'else printf "Source: 1\\n"; fi\n',
            )
            item = spool / "ready-MIC"
            item.mkdir(parents=True)
            (item / "summary.txt").write_text("Claude needs approval")
            (item / "announcement.wav").write_bytes(b"RIFF")
            result = subprocess.run(
                [
                    "bash", str(FOOT), "dispatch", "claude-ai-notifs", "ready-MIC",
                    "foot", "", "", "normal", "-1", "0", "false", "",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text()
            self.assertIn("notify:", calls)
            self.assertIn("suppress-sound:true", calls)
            self.assertNotIn("paplay:", calls)

    def test_internal_token_cannot_escape_private_spool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env, _spool, log = self.environment(root)
            outside = root / "outside"
            outside.mkdir()
            (outside / "summary.txt").write_text("do not consume")
            result = subprocess.run(
                [
                    "bash", str(FOOT), "dispatch", "claude-ai-notifs", "../outside",
                    "foot", "", "", "normal", "-1", "0", "false", "",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(outside.is_dir())
            self.assertFalse(log.exists())


if __name__ == "__main__":
    unittest.main()
