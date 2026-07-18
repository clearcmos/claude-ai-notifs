#!/bin/bash
# Verify the hook's real dbg() QA-log rotation: the log rotates to debug.log.1
# once it exceeds DEBUG_LOG_MAX, at most once per invocation, keeping exactly
# one prior generation, and the active log is kept 0600. The foot dispatcher
# carries the same rotation block.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/bin/claude-announce"

FNS="$(mktemp)"
BASE="$(mktemp -d)"
trap 'rm -rf "$FNS" "$BASE"' EXIT

awk '/^dbg\(\) \{/{f=1} f{print} /^\}/{if(f)exit}' "$SRC" > "$FNS"
grep -q 'DBG_ROTATED' "$FNS" || { echo "FAIL: could not extract dbg() with rotation"; exit 1; }
# shellcheck disable=SC1090
. "$FNS"

fail() { echo "FAIL: $1" >&2; exit 1; }

mode() {
    case "$(uname -s)" in
        Darwin) stat -f '%Lp' "$1" ;;
        *)      stat -c '%a' "$1" ;;
    esac
}

# Variables the sourced dbg reads (SC2034: only the sourced function, which
# ShellCheck cannot follow, reads them). A small cap keeps the test fast.
DEBUG_LOG="$BASE/debug.log"
# shellcheck disable=SC2034
DEBUG_LOG_MAX=4096
# shellcheck disable=SC2034
DBG_ROTATED=""
# shellcheck disable=SC2034
MODE="test"
# shellcheck disable=SC2034
CLAUDE_ANNOUNCE_DEBUG=1

# 1) A small log is appended to and never rotated.
printf 'existing trace\n' > "$DEBUG_LOG"
dbg "first line"
[ ! -e "$DEBUG_LOG.1" ] || fail "small log must not rotate"
grep -q 'existing trace' "$DEBUG_LOG" || fail "small log lost existing content"
grep -q 'first line' "$DEBUG_LOG" || fail "dbg did not append"
echo "PASS: small log appends without rotation"

# 2) An oversized log rotates: prior content moves whole to debug.log.1 and the
# fresh log starts with just the new line.
# shellcheck disable=SC2034
DBG_ROTATED=""
head -c $((DEBUG_LOG_MAX + 100)) /dev/zero | tr '\0' 'x' > "$DEBUG_LOG"
dbg "after rotation"
[ -s "$DEBUG_LOG.1" ] || fail "oversized log did not rotate to debug.log.1"
grep -q 'x' "$DEBUG_LOG.1" || fail "rotated generation lost the old content"
grep -q 'after rotation' "$DEBUG_LOG" || fail "post-rotation append missing"
grep -q 'x' "$DEBUG_LOG" && fail "old content should live only in debug.log.1"
echo "PASS: oversized log rotates and keeps one prior generation"

# 3) Rotation runs at most once per invocation: even if the log passes the cap
# again in the same process, the kept generation is not replaced, so a chatty
# run cannot discard its own fresh trace.
head -c $((DEBUG_LOG_MAX + 100)) /dev/zero | tr '\0' 'y' >> "$DEBUG_LOG"
dbg "same invocation"
grep -q 'y' "$DEBUG_LOG.1" && fail "second rotation replaced the kept generation"
grep -q 'x' "$DEBUG_LOG.1" || fail "kept generation changed within one invocation"
grep -q 'same invocation' "$DEBUG_LOG" || fail "append after the cap missed"
echo "PASS: rotation happens at most once per invocation"

# 4) The active log is tightened to 0600 on append.
[ "$(mode "$DEBUG_LOG")" = 600 ] || fail "debug.log should be 0600, got $(mode "$DEBUG_LOG")"
echo "PASS: active log kept 0600"

echo "OK"
