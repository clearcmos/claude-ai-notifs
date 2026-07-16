#!/bin/bash
# Pure host-terminal detection tests using the real function from the hook.
# Variables below are consumed by that dynamically sourced function.
# shellcheck disable=SC2034
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
FNS="$(mktemp)"
SETUP_FNS="$(mktemp)"
trap 'rm -f "$FNS" "$SETUP_FNS"' EXIT

awk '/^host_terminal\(\) \{/{f=1} f{print} f && /^\}/{exit}' \
    "$REPO/bin/claude-announce" > "$FNS"
# shellcheck disable=SC1090
. "$FNS"

awk '/^terminal_installed\(\) \{/{f=1} f{print} f && /^\}/{exit}' \
    "$REPO/setup.sh" > "$SETUP_FNS"
# shellcheck disable=SC1090
. "$SETUP_FNS"

reset_env() {
    KITTY_WINDOW_ID=""
    WEZTERM_PANE=""
    GHOSTTY_RESOURCES_DIR=""
    GHOSTTY_SURFACE_ID=""
    ALACRITTY_WINDOW_ID=""
    ALACRITTY_SOCKET=""
    ITERM_SESSION_ID=""
    TERM_PROGRAM=""
    TERM=""
}

assert_host() {
    expected="$1"
    actual=$(host_terminal)
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: expected host '$expected', got '$actual'" >&2
        exit 1
    fi
}

reset_env; KITTY_WINDOW_ID=1; TERM_PROGRAM=Apple_Terminal; assert_host kitty
reset_env; WEZTERM_PANE=2; assert_host wezterm
reset_env; GHOSTTY_SURFACE_ID=3; assert_host ghostty
reset_env; ALACRITTY_WINDOW_ID=4; assert_host alacritty
reset_env; ITERM_SESSION_ID=5; assert_host iterm2
reset_env; TERM_PROGRAM=Apple_Terminal; assert_host terminal
reset_env; TERM_PROGRAM=WezTerm; assert_host wezterm
reset_env; TERM=xterm-kitty; assert_host kitty
reset_env; TERM=xterm-ghostty; assert_host ghostty
reset_env; assert_host ""

# Regression: under pipefail, the old `mdfind | grep -q` returned failure when
# enough matches made mdfind hit SIGPIPE after grep exited on its first line.
mdfind() {
    i=0
    while [ "$i" -lt 10000 ]; do
        printf '/nonstandard/App%s.app\n' "$i"
        i=$((i + 1))
    done
}
set -o pipefail
terminal_installed com.example.Nonstandard \
    || { echo "FAIL: Spotlight match lost under pipefail" >&2; exit 1; }

echo "PASS: host detection, precedence, and pipefail-safe app discovery"
