#!/usr/bin/env python
"""Kokoro TTS helper for claude-announce.

Usage: claude-announce-tts.py TEXT OUTPUT_WAV

Runs inside the venv at ~/.local/share/claude-ai-notifs/venv (kokoro-onnx,
soundfile). Synthesizes TEXT with the af_heart voice (US English, female,
same voice as the Linux setup) and writes a wav to OUTPUT_WAV. CPU
inference; a one-sentence announcement takes a couple of seconds including
model load.
"""

import os
import sys

from kokoro_onnx import Kokoro
import soundfile as sf


def main():
    if len(sys.argv) != 3:
        sys.exit(2)
    text, out = sys.argv[1], sys.argv[2]

    base = os.path.expanduser("~/.local/share/claude-ai-notifs")
    kokoro = Kokoro(
        os.path.join(base, "kokoro-v1.0.onnx"),
        os.path.join(base, "voices-v1.0.bin"),
    )
    samples, sample_rate = kokoro.create(
        text, voice="af_heart", speed=1.05, lang="en-us")
    sf.write(out, samples, sample_rate)


if __name__ == "__main__":
    main()
