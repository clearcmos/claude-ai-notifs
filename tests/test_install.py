#!/usr/bin/env python3
"""Tests for the self-contained, atomic runtime installation."""

import importlib.util
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL_PATH = ROOT / "bin" / "claude-announce-install.py"
_spec = importlib.util.spec_from_file_location("claude_announce_install", INSTALL_PATH)
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)


def fake_repo(parent):
    repo = pathlib.Path(parent) / "source-checkout"
    target = repo / "bin"
    target.mkdir(parents=True)
    for name in installer.RUNTIME_FILES:
        shutil.copyfile(ROOT / "bin" / name, target / name)
    return repo


class RuntimeInstall(unittest.TestCase):
    def test_install_survives_deleting_source_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            repo = fake_repo(root)
            base = root / "home" / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(repo, base)

            self.assertTrue(current.is_symlink())
            self.assertFalse(os.path.isabs(os.readlink(current)))
            for name in installer.RUNTIME_FILES:
                path = current / "bin" / name
                self.assertTrue(path.is_file())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

            shutil.rmtree(repo)
            source = "I investigated Okta access."
            assessment = json.dumps({
                "status": "investigated",
                "evidence": "investigated",
                "topic": "Okta access",
            })
            result = subprocess.run(
                [sys.executable, str(current / "bin" / "claude-announce-render.py"),
                 "--", source],
                input=assessment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "Investigated Okta access.")

    def test_upgrade_atomically_switches_current_and_keeps_old_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            repo = fake_repo(root)
            base = root / "base"
            current = installer.install_runtime(repo, base)
            old_target = os.readlink(current)
            old_release = (current.parent / old_target).resolve()

            marker = "\n# upgraded test marker\n"
            with open(repo / "bin" / "claude-announce", "a") as file:
                file.write(marker)
            installer.install_runtime(repo, base)

            self.assertNotEqual(os.readlink(current), old_target)
            self.assertTrue(old_release.is_dir())
            self.assertIn(marker.strip(),
                          (current / "bin" / "claude-announce").read_text())

    def test_failed_upgrade_leaves_current_release_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            repo = fake_repo(root)
            base = root / "base"
            current = installer.install_runtime(repo, base)
            target = os.readlink(current)
            (repo / "bin" / "claude-announce-render.py").unlink()

            with self.assertRaises(FileNotFoundError):
                installer.install_runtime(repo, base)
            self.assertEqual(os.readlink(current), target)
            self.assertTrue((current / "bin" / "claude-announce").is_file())

    def test_installed_uninstaller_works_without_source_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            repo = fake_repo(directory)
            base = home / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(repo, base)
            announce = str(current / "bin" / "claude-announce")
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({
                "hooks": {
                    "Stop": [{"hooks": [{
                        "type": "command", "command": announce,
                        "args": ["stop"], "async": True,
                    }]}, {"hooks": [{"type": "command", "command": "keepme"}]}],
                    "PreToolUse": [{
                        "matcher": "^AskUserQuestion$",
                        "hooks": [{
                            "type": "command", "command": announce,
                            "args": ["ask"], "async": True,
                        }],
                    }, {
                        "matcher": "Write",
                        "hooks": [{"type": "command", "command": "keep-pretool"}],
                    }],
                    "PermissionRequest": [{"hooks": [{
                        "type": "command", "command": announce,
                        "args": ["permission"], "async": True,
                    }]}],
                    "Notification": [{"hooks": [{
                        "type": "command", "command": announce,
                        "args": ["notification"], "async": True,
                    }]}],
                }
            }))
            uninstaller = current / "bin" / "claude-announce-uninstall"
            shutil.rmtree(repo)

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["CLAUDE_SETTINGS"] = str(settings)
            result = subprocess.run(
                [str(uninstaller)], env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(base.exists())
            installed = json.loads(settings.read_text())
            commands = [
                hook["command"]
                for entry in installed["hooks"]["Stop"]
                for hook in entry["hooks"]
            ]
            self.assertEqual(commands, ["keepme"])
            self.assertEqual(
                installed["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
                "keep-pretool",
            )
            self.assertNotIn("PermissionRequest", installed["hooks"])
            self.assertNotIn("Notification", installed["hooks"])

    def test_uninstaller_keeps_runtime_when_settings_are_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            repo = fake_repo(directory)
            base = home / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(repo, base)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text("{ invalid json")
            uninstaller = current / "bin" / "claude-announce-uninstall"

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["CLAUDE_SETTINGS"] = str(settings)
            result = subprocess.run(
                [str(uninstaller)], env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(base.is_dir())
            self.assertIn("Nothing was deleted", result.stdout)

    def test_uninstaller_restores_managed_foot_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            repo = fake_repo(directory)
            base = home / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(repo, base)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text("{}\n")
            config = home / ".config" / "foot" / "foot.ini"
            config.parent.mkdir(parents=True)
            original = "[main]\nfont=monospace\n"
            config.write_text(original)
            configured = subprocess.run(
                [
                    sys.executable,
                    str(current / "bin" / "claude-announce-foot-config.py"),
                    "configure",
                    str(config),
                    str(current / "bin" / "claude-announce-foot"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stderr)
            (base / "foot-config-path").write_text(str(config) + "\n")

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["CLAUDE_SETTINGS"] = str(settings)
            result = subprocess.run(
                [str(current / "bin" / "claude-announce-uninstall")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(config.read_text(), original)
            self.assertFalse(base.exists())

    def test_uninstaller_keeps_runtime_when_foot_restore_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory) / "home"
            repo = fake_repo(directory)
            base = home / ".local" / "share" / "claude-ai-notifs"
            current = installer.install_runtime(repo, base)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text("{}\n")
            config = home / ".config" / "foot" / "foot.ini"
            config.parent.mkdir(parents=True)
            config.write_text("# claude-ai-notifs: begin managed foot notification adapter\n")
            (base / "foot-config-path").write_text(str(config) + "\n")

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["CLAUDE_SETTINGS"] = str(settings)
            result = subprocess.run(
                [str(current / "bin" / "claude-announce-uninstall")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(base.is_dir())
            self.assertIn("nothing under", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
