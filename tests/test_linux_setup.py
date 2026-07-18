#!/usr/bin/env python3

import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.uname().sysname == "Linux", "Linux setup dispatch test")
class LinuxSetupTests(unittest.TestCase):
    def test_public_entrypoint_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            home.mkdir()
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(home / "config")
            env["CLAUDE_SETTINGS"] = str(home / "claude-settings.json")
            result = subprocess.run(
                [str(ROOT / "setup.sh"), "--dry-run"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Linux preflight", result.stdout)
            self.assertIn("no files, packages, services, models, or settings were changed", result.stdout)
            self.assertFalse((home / ".local" / "share" / "claude-ai-notifs").exists())
            self.assertFalse((home / "claude-settings.json").exists())

    def test_options_are_order_independent_and_relative_config_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            launch = pathlib.Path(directory) / "launch"
            home.mkdir()
            launch.mkdir()
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(home / "config")
            result = subprocess.run(
                [str(ROOT / "setup.sh"), "--yes", "--foot-config", "foot.ini", "--dry-run"],
                cwd=launch,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("foot config: " + str(launch / "foot.ini"), result.stdout)
            self.assertFalse((launch / "foot.ini").exists())

    def test_uninstall_action_can_follow_other_options(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            home.mkdir()
            env = os.environ.copy()
            env["HOME"] = str(home)
            result = subprocess.run(
                [str(ROOT / "setup.sh"), "--yes", "--uninstall"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("uninstalled", result.stdout)
            self.assertNotIn("Linux preflight", result.stdout)


if __name__ == "__main__":
    unittest.main()
