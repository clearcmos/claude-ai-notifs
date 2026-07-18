#!/bin/bash
# Verify the hook's real clean() summary normalization: double quotes dropped,
# whitespace collapsed, and a 300-CHARACTER cap. Regression: the old byte cap
# (head -c 300) could split a multibyte character and hand invalid UTF-8 to
# TTS or notify-send.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/bin/claude-announce"

PY="$(command -v python3)" || { echo "SKIP: python3 not available"; exit 0; }

FNS="$(mktemp)"
trap 'rm -rf "$FNS"' EXIT
awk '/^clean\(\) \{/{f=1} f{print} /^\}/{if(f)exit}' "$SRC" > "$FNS"
grep -q 'clean()' "$FNS" || { echo "FAIL: could not extract clean()"; exit 1; }
# shellcheck disable=SC1090
. "$FNS"

fail() { echo "FAIL: $1" >&2; exit 1; }

# 1) A multibyte character at the cap boundary survives intact: the output is
# valid UTF-8 and exactly 300 characters (299 ASCII + one 2-byte character).
"$PY" -c 'import sys; sys.stdout.write("a" * 299 + "é" * 10)' | clean \
    | "$PY" -c '
import sys
text = sys.stdin.buffer.read().decode("utf-8")   # raises on a split character
assert len(text) == 300, "expected 300 characters, got %d" % len(text)
assert text == "a" * 299 + "é", "unexpected tail: %r" % text[-3:]
' || fail "multibyte truncation split a character or missed the 300-char cap"
echo "PASS: character cap never splits multibyte UTF-8"

# 2) ASCII longer than the cap is truncated to exactly 300 characters.
out=$("$PY" -c 'import sys; sys.stdout.write("b" * 400)' | clean)
[ "${#out}" -eq 300 ] || fail "ASCII cap produced ${#out} characters, not 300"
echo "PASS: 300-character cap on plain ASCII"

# 3) Double quotes are dropped and internal whitespace runs collapse, with
# leading/trailing whitespace trimmed.
out=$(printf '  say \n"hello   there"\t now ' | clean)
[ "$out" = "say hello there now" ] || fail "normalization produced [$out]"
echo "PASS: quotes dropped and whitespace collapsed"

# 4) Short clean input passes through unchanged.
out=$(printf 'Made changes to the tests.' | clean)
[ "$out" = "Made changes to the tests." ] || fail "short input was altered: [$out]"
echo "PASS: short input passes through unchanged"

echo "OK"
