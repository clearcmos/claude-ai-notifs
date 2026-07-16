#!/usr/bin/env python3
"""Unit tests for the Kokoro TTS adapter without loading model files."""

import importlib.util
import os
import pathlib
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "bin" / "claude-announce-tts.py"


class FakeKokoro:
    instances = []

    def __init__(self, model, voices):
        self.model = model
        self.voices = voices
        self.calls = []
        self.__class__.instances.append(self)

    def create(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return [0.0], 24000


def fake_write(path, samples, sample_rate):
    del samples, sample_rate
    with open(path, "wb") as output:
        output.write(b"RIFF")


def load_tts():
    spec = importlib.util.spec_from_file_location("claude_announce_tts", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    fake_kokoro = types.SimpleNamespace(Kokoro=FakeKokoro)
    fake_soundfile = types.SimpleNamespace(write=fake_write)
    with mock.patch.dict(
            sys.modules,
            {"kokoro_onnx": fake_kokoro, "soundfile": fake_soundfile}):
        spec.loader.exec_module(module)
    return module


class TextToSpeech(unittest.TestCase):
    def setUp(self):
        FakeKokoro.instances.clear()
        self.tts = load_tts()

    def test_usage_error(self):
        with mock.patch.object(sys, "argv", [str(MODULE_PATH)]):
            with self.assertRaisesRegex(SystemExit, "2"):
                self.tts.main()

    def test_synthesis_uses_private_output_and_expected_voice(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "announcement.wav"
            previous_umask = os.umask(0)
            try:
                with mock.patch.object(
                        sys, "argv", [str(MODULE_PATH), "Finished safely", str(output)]):
                    self.tts.main()
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            instance = FakeKokoro.instances[0]
            self.assertTrue(instance.model.endswith("/kokoro-v1.0.onnx"))
            self.assertTrue(instance.voices.endswith("/voices-v1.0.bin"))
            self.assertEqual(
                instance.calls,
                [("Finished safely", {
                    "voice": "af_heart",
                    "speed": 1.05,
                    "lang": "en-us",
                })],
            )


if __name__ == "__main__":
    unittest.main()
