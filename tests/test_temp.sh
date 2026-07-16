#!/bin/bash
# Verify the hook's real temporary-WAV functions on BSD and GNU mktemp/stat.
set -u
umask 077

REPO="$(cd "$(dirname "$0")/.." && pwd)"
FNS="$(mktemp)"
BASE="$(mktemp -d)"
trap 'rm -rf "$FNS" "$BASE"' EXIT

# Source make_wav_temp and cleanup_wav verbatim from the hook.
awk '/^make_wav_temp\(\) \{/{f=1} f{print} f && /^cleanup_wav\(\)/{exit}' \
    "$REPO/bin/claude-announce" > "$FNS"
# shellcheck disable=SC1090
. "$FNS"

mode() {
    case "$(uname -s)" in
        Darwin) stat -f '%Lp' "$1" ;;
        *)      stat -c '%a' "$1" ;;
    esac
}

TMPDIR="$BASE"
wav_dir=""; wav=""
make_wav_temp || { echo "FAIL: make_wav_temp failed" >&2; exit 1; }
[ -d "$wav_dir" ] || { echo "FAIL: temp directory missing" >&2; exit 1; }
[ "$(mode "$wav_dir")" = 700 ] || { echo "FAIL: temp directory is not 0700" >&2; exit 1; }
[ "${wav##*/}" = announcement.wav ] || { echo "FAIL: unexpected WAV path" >&2; exit 1; }
[ "${wav_dir##*/}" != 'claude-announce.XXXXXX' ] \
    || { echo "FAIL: mktemp template was not randomized" >&2; exit 1; }

: > "$wav"
[ "$(mode "$wav")" = 600 ] || { echo "FAIL: WAV is not 0600" >&2; exit 1; }
cleanup_wav
[ ! -e "$wav_dir" ] || { echo "FAIL: temp directory was not removed" >&2; exit 1; }

echo "PASS: private randomized WAV directory and cleanup"
