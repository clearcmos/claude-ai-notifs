#!/bin/bash
# Regression test for the macOS playback fallback chain: kokoro wav via
# afplay, then native say, then the ding asset. Sources play_summary verbatim
# from the hook script and stubs the players as shell functions, so the chain
# logic is exercised on any OS.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/bin/claude-announce"

FNS="$(mktemp)"
WORK="$(mktemp -d)"
awk '/^play_summary\(\) \{/{f=1} f{print} /^\}/{if(f)exit}' "$SRC" > "$FNS"
grep -q "play_summary" "$FNS" || { echo "FAIL: could not extract play_summary"; exit 1; }
# shellcheck disable=SC1090
. "$FNS"

fail() { echo "FAIL: $1" >&2; rm -rf "$WORK" "$FNS"; exit 1; }

CALLS="$WORK/calls"
dbg() { :; }
with_timeout() { shift; "$@"; }

# Stub players. AFPLAY_RC / SAY_RC select each stub's exit status per
# scenario; afplay consults AFPLAY_DING_RC for the ding asset so the wav
# attempt and the ding attempt can succeed or fail independently.
afplay() {
    echo "afplay $1" >> "$CALLS"
    if [ "$1" = "$DING" ]; then return "${AFPLAY_DING_RC:-$AFPLAY_RC}"; fi
    return "$AFPLAY_RC"
}
say() { echo "say $1" >> "$CALLS"; return "$SAY_RC"; }

reset() { : > "$CALLS"; }
DING="/fake/ding.aiff"
summary="Explained the playback chain."

# 1) Good wav: afplay plays it; say and ding are never touched.
reset; AFPLAY_RC=0 SAY_RC=0
wav="$WORK/good.wav"; printf 'RIFF' > "$wav"
play_summary || fail "play_summary reported failure on the happy path"
[ "$(cat "$CALLS")" = "afplay $wav" ] || { cat "$CALLS"; fail "happy path should be a single afplay of the wav"; }
echo "PASS: good wav plays once via afplay"

# 2) Truncated/corrupt wav (afplay fails): falls back to say with the summary.
reset; AFPLAY_RC=1 SAY_RC=0
play_summary || fail "say fallback should report success"
printf 'afplay %s\nsay %s\n' "$wav" "$summary" | cmp -s - "$CALLS" \
    || { cat "$CALLS"; fail "afplay failure must fall back to say \$summary"; }
echo "PASS: failed afplay falls back to say"

# 3) afplay and say both fail: the ding asset is the terminal fallback, and a
# ding that plays successfully makes the whole chain report success.
reset; AFPLAY_RC=1 SAY_RC=1 AFPLAY_DING_RC=0
play_summary || fail "a successful ding must make play_summary succeed"
grep -qx "say $summary" "$CALLS" || { cat "$CALLS"; fail "say was not attempted"; }
tail -n 1 "$CALLS" | grep -qx "afplay $DING" \
    || { cat "$CALLS"; fail "failed say must fall back to the ding asset"; }
echo "PASS: failed say falls back to a successful ding"

# 4) No wav at all: say is the first attempt, no wav afplay call.
reset; AFPLAY_RC=0 SAY_RC=0
wav="$WORK/missing.wav"
play_summary || fail "missing wav should still speak via say"
[ "$(cat "$CALLS")" = "say $summary" ] || { cat "$CALLS"; fail "missing wav should go straight to say"; }
echo "PASS: missing wav goes straight to say"

# 5) Everything failing, ding included, is reflected in the exit status.
reset; AFPLAY_RC=1 SAY_RC=1 AFPLAY_DING_RC=1
if play_summary; then fail "all-players-failed should not report success"; fi
echo "PASS: total playback failure is reported, not masked"

rm -rf "$WORK" "$FNS"
echo "OK"
