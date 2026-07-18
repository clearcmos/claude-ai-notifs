#!/bin/bash
# Concurrency test for the claude-announce audio lock (macOS lockf fd-locking).
# Proves concurrent holders serialize and that a killed holder's lock is
# released automatically by the kernel. Skips (exit 0) only on Linux, whose
# runtime serializes via flock in the foot dispatcher instead; on macOS the
# entire serialization design rests on lockf, so its absence is a FAILURE, not
# a skip - otherwise CI would stay green while lock coverage silently vanished.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/bin/claude-announce"

if ! command -v lockf >/dev/null 2>&1; then
    if [ "$(uname -s)" = "Darwin" ]; then
        echo "FAIL: lockf is missing on macOS; audio serialization would be a silent no-op" >&2
        exit 1
    fi
    echo "SKIP: lockf not available (Linux serializes via flock in the foot dispatcher)"
    exit 0
fi

# Source the two lock functions verbatim from the hook script.
FNS="$(mktemp)"
awk '/^audio_lock\(\) \{/{f=1} f{print} /^\}/{if(f)c++} c==2{exit}' "$SRC" > "$FNS"
BASE="$(mktemp -d)"
# AUDIO_LOCK / AUDIO_LOCK_WAIT are read by the sourced audio_lock/audio_unlock.
# shellcheck disable=SC2034
AUDIO_LOCK="$BASE/audio.lock"
# shellcheck disable=SC2034
AUDIO_LOCK_WAIT=30
# shellcheck disable=SC1090
. "$FNS"

fail() { echo "FAIL: $1" >&2; rm -rf "$BASE" "$FNS"; exit 1; }

# 1) Mutual exclusion: concurrent workers must not interleave start/end markers.
OUT="$BASE/out"; : > "$OUT"
worker() { ( audio_lock; echo "start $1" >> "$OUT"; sleep 0.4; echo "end $1" >> "$OUT"; audio_unlock ); }
worker A & worker B & worker C & wait
python3 -c '
import sys
xs=[l.split()[0] for l in open(sys.argv[1]) if l.strip()]
ok = len(xs) % 2 == 0 and all(xs[i]=="start" and xs[i+1]=="end" for i in range(0,len(xs),2))
sys.exit(0 if ok else 1)
' "$OUT" || { cat "$OUT"; fail "workers interleaved (not serialized)"; }
echo "PASS: 3 concurrent workers serialized"

# 2) Auto-release on kill: exec sleep so the killed PID is the sole fd holder.
( audio_lock; exec sleep 10 ) & holder=$!
sleep 0.3
kill -9 "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
( audio_lock; : > "$BASE/acq"; audio_unlock ) & w=$!
( sleep 5; kill -9 "$w" 2>/dev/null ) & wd=$!
wait "$w" 2>/dev/null; kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
[ -f "$BASE/acq" ] || fail "lock not released after holder was killed"
echo "PASS: lock auto-released after holder killed"

rm -rf "$BASE" "$FNS"
echo "OK"
