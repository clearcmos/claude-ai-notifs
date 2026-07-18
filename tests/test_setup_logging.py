#!/usr/bin/env python3

import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent


class SetupLoggingTests(unittest.TestCase):
    def environment(self, home):
        env = os.environ.copy()
        env["HOME"] = str(home)
        env.pop("CLAUDE_ANNOUNCE_DEBUG", None)
        return env

    def installed_runtime(self, home):
        announce = (
            home / ".local" / "share" / "claude-ai-notifs"
            / "runtime" / "current" / "bin" / "claude-announce"
        )
        announce.parent.mkdir(parents=True)
        announce.write_text("#!/bin/sh\nexit 0\n")
        announce.chmod(0o700)
        return announce

    def run_setup(self, home, option):
        return subprocess.run(
            [str(ROOT / "setup.sh"), option],
            cwd=ROOT,
            env=self.environment(home),
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )

    def test_existing_install_can_toggle_private_log_without_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            home.mkdir()
            self.installed_runtime(home)
            base = home / ".local" / "share" / "claude-ai-notifs"
            log = base / "debug.log"
            log.write_text("existing trace\n")
            log.chmod(0o644)

            enabled = self.run_setup(home, "--log-on")
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            self.assertIn("QA logging enabled", enabled.stdout)
            self.assertNotIn("Linux preflight", enabled.stdout)
            self.assertTrue((base / "debug").is_file())
            self.assertEqual(stat.S_IMODE((base / "debug").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
            self.assertIn("existing trace", log.read_text())
            self.assertIn("logging enabled", log.read_text())

            disabled = self.run_setup(home, "--log-off")
            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            self.assertIn("QA logging disabled", disabled.stdout)
            self.assertFalse((base / "debug").exists())
            self.assertTrue(log.is_file())
            self.assertIn("logging disabled", log.read_text())

    def test_log_off_without_install_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            home.mkdir()
            result = self.run_setup(home, "--log-off")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("QA logging disabled", result.stdout)
            self.assertFalse(
                (home / ".local" / "share" / "claude-ai-notifs").exists()
            )

    def test_logging_options_must_be_standalone(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            home.mkdir()
            for script in ("setup.sh", "setup-linux.sh"):
                with self.subTest(script=script):
                    result = subprocess.run(
                        [str(ROOT / script), "--log-on", "--dry-run"],
                        cwd=ROOT,
                        env=self.environment(home),
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=15,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("must be used by themselves", result.stderr)
            self.assertFalse(
                (home / ".local" / "share" / "claude-ai-notifs").exists()
            )


if __name__ == "__main__":
    unittest.main()
