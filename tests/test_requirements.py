#!/usr/bin/env python3
"""Keep the human-edited direct pins synchronized with requirements.lock."""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


def canonical_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path):
    found = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = PIN.match(raw.strip())
        if not match:
            continue
        name, version = match.groups()
        found[canonical_name(name)] = version
    return found


class RequirementsLock(unittest.TestCase):
    def test_direct_pins_match_generated_lock(self):
        direct = pins(ROOT / "requirements.txt")
        locked = pins(ROOT / "requirements.lock")
        self.assertTrue(direct, "requirements.txt contains no exact direct pins")
        for name, version in direct.items():
            self.assertIn(name, locked, f"{name} is missing from requirements.lock")
            self.assertEqual(
                locked[name], version,
                f"{name} drifted: requirements.txt={version}, "
                f"requirements.lock={locked[name]}",
            )


if __name__ == "__main__":
    unittest.main()
