#!/usr/bin/env python3
"""Generate the small built-in Linux fallback ding using only the stdlib."""

import math
import os
import struct
import sys
import tempfile
import wave


def generate(path):
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".ding.", suffix=".wav")
    os.close(fd)
    try:
        rate = 24000
        duration = 0.22
        frames = bytearray()
        for index in range(int(rate * duration)):
            time = index / rate
            decay = math.exp(-13 * time)
            sample = 0.34 * decay * (
                math.sin(2 * math.pi * 880 * time)
                + 0.45 * math.sin(2 * math.pi * 1320 * time)
            )
            sample = max(-1.0, min(1.0, sample))
            frames.extend(struct.pack("<h", int(sample * 32767)))
        with wave.open(temporary, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(frames)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main(argv):
    if len(argv) != 2:
        print("usage: claude-announce-ding.py OUTPUT.wav", file=sys.stderr)
        return 64
    try:
        generate(argv[1])
    except OSError as error:
        print("could not generate fallback ding: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
