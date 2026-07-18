#!/usr/bin/env python3

import contextlib
import importlib.util
import io
import os
import pathlib
import stat
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "bin" / "claude-announce-foot-config.py"
SPEC = importlib.util.spec_from_file_location("foot_config", PATH)
foot_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(foot_config)


class FootConfigTests(unittest.TestCase):
    def test_configure_new_file_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot" / "foot.ini"
            dispatcher = pathlib.Path(directory) / "home with spaces" / "dispatcher"
            foot_config.configure(config, dispatcher)

            text = config.read_text()
            self.assertIn(foot_config.BEGIN, text)
            self.assertIn('"' + str(dispatcher) + '" dispatch', text)
            self.assertIn("${title} ${body}", text)
            self.assertIn(
                "command-action-argument=--action ${action-name}=${action-label}",
                text,
            )
            self.assertIn("inhibit-when-focused=yes", text)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)

            self.assertTrue(foot_config.restore(config))
            self.assertEqual(config.read_text(), "")

    def test_restore_is_a_noop_on_untouched_or_missing_config(self):
        # setup records foot-config-path BEFORE writing the managed block, so
        # uninstall must treat a recorded-but-never-configured (or absent)
        # config as nothing-to-do, never as a failure that strands $BASE.
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot" / "foot.ini"
            self.assertFalse(foot_config.restore(config))
            config.parent.mkdir(parents=True)
            config.write_text("[main]\nfont=monospace:size=10\n")
            self.assertFalse(foot_config.restore(config))
            self.assertEqual(
                config.read_text(), "[main]\nfont=monospace:size=10\n"
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(foot_config.main(["restore", str(config)]), 0)

    def test_custom_command_requires_force_and_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot.ini"
            original = (
                "[main]\nfont=monospace:size=11\n\n"
                "[desktop-notifications]\ncommand=my-notifier ${title}\n"
            )
            config.write_text(original)
            with self.assertRaises(foot_config.ConfigConflict):
                foot_config.configure(config, "/tmp/dispatcher")

            foot_config.configure(config, "/tmp/dispatcher", force=True)
            configured = config.read_text()
            self.assertIn("command=my-notifier ${title}", configured)
            self.assertIn(foot_config.BEGIN, configured)
            self.assertIsNone(foot_config.configure(config, "/tmp/dispatcher"))
            foot_config.restore(config)
            self.assertEqual(config.read_text(), original)

    def test_disabled_inhibition_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot.ini"
            config.write_text(
                "[desktop-notifications]\ninhibit-when-focused=no\n"
            )
            state = foot_config.inspect_config(config)
            self.assertTrue(state["inhibit_disabled"])
            with self.assertRaises(foot_config.ConfigConflict):
                foot_config.configure(config, "/tmp/dispatcher")

    def test_custom_action_template_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot.ini"
            config.write_text(
                "[desktop-notifications]\n"
                "command-action-argument=--custom ${action-name}\n"
            )
            with self.assertRaises(foot_config.ConfigConflict):
                foot_config.configure(config, "/tmp/dispatcher")

    def test_configure_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot.ini"
            config.write_text("[main]\nfont=monospace\n")
            foot_config.configure(config, "/tmp/dispatcher")
            first = config.read_text()
            result = foot_config.configure(config, "/tmp/dispatcher")
            self.assertIsNone(result)
            self.assertEqual(config.read_text(), first)
            self.assertEqual(config.read_text().count(foot_config.BEGIN), 1)

    def test_rerun_moves_managed_block_after_later_user_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot.ini"
            config.write_text("[main]\nfont=monospace\n")
            foot_config.configure(config, "/tmp/dispatcher")
            with config.open("a") as handle:
                handle.write("[desktop-notifications]\ninhibit-when-focused=no\n")

            foot_config.configure(config, "/tmp/dispatcher")
            text = config.read_text()
            self.assertGreater(text.rfind(foot_config.BEGIN), text.rfind("inhibit-when-focused=no"))
            self.assertEqual(text.count(foot_config.BEGIN), 1)

            foot_config.restore(config)
            self.assertIn("inhibit-when-focused=no", config.read_text())

    def test_symlinked_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            target = root / "dotfiles" / "foot.ini"
            target.parent.mkdir()
            target.write_text("[main]\nfont=monospace\n")
            config = root / "config" / "foot.ini"
            config.parent.mkdir()
            config.symlink_to(target)

            destination = foot_config.configure(config, "/tmp/dispatcher")
            self.assertTrue(config.is_symlink())
            self.assertIn(foot_config.BEGIN, target.read_text())
            self.assertTrue(pathlib.Path(destination).parent.samefile(config.parent))
            self.assertFalse(any(".bak." in path.name for path in target.parent.iterdir()))

            foot_config.restore(config)
            self.assertTrue(config.is_symlink())
            self.assertEqual(target.read_text(), "[main]\nfont=monospace\n")

    def test_orphaned_marker_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "foot.ini"
            config.write_text(foot_config.BEGIN + "\n")
            with self.assertRaises(ValueError):
                foot_config.configure(config, "/tmp/dispatcher")


if __name__ == "__main__":
    unittest.main()
