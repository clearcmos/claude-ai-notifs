#!/bin/bash
# Setup for claude-ai-notifs. Linux dispatches to setup-linux.sh; the remainder
# of this file is the macOS installer. Both paths are idempotent and safe to
# re-run after pulling changes.
#
#   ./setup.sh              full setup: venv, models, summarizer, terminals, hooks
#   ./setup.sh --terminals "ghostty,iterm2"
#                           non-interactive terminal selection (keys, comma/space)
#   ./setup.sh --summarizer apple|ollama
#                           non-interactive summarizer selection (re-run to switch)
#   ./setup.sh --model NAME Ollama model to provision (default picked by RAM)
#   ./setup.sh --ollama-host URL
#                           use this explicit Ollama API endpoint
#   ./setup.sh --yes        assume yes for install/download confirmations
#   ./setup.sh --test       after setup: run one end-to-end spoken announcement
#                           against the most recent Claude transcript
#   ./setup.sh --uninstall  remove the hooks and installed runtime; the same
#                           uninstaller is also copied into the runtime
#   ./setup.sh --log-on     enable the private QA trace (installs first if needed)
#   ./setup.sh --log-off    disable the QA trace but retain debug.log for review
#
# What it does:
#   1. Checks prerequisites (Apple Silicon, Xcode CLT, Python 3.12+) and reports
#      whether macOS 26's optional on-device summarizer is available.
#   2. Creates the Kokoro TTS venv and downloads the model files (~340 MB)
#      into ~/.local/share/claude-ai-notifs.
#   3. Compiles the Apple Foundation Models summarizer with swiftc and reports
#      whether Apple Intelligence is enabled.
#   4. Asks whether announcements summarize with the Apple on-device model or
#      a local Ollama model (re-run to switch). Choosing Ollama provisions it:
#      reuse a reachable API, start an installed server, or offer a Homebrew
#      install, then pull the selected model and record the choice in
#      ~/.local/share/claude-ai-notifs/summarizer. Apple and claude -p remain
#      runtime fallbacks either way.
#   5. Installs all runtime scripts as an atomic, versioned release under
#      ~/.local/share/claude-ai-notifs/runtime; the repo is not needed at runtime.
#   6. Asks which installed terminals to announce in (multi-select; re-run to
#      add more) and records them in ~/.local/share/claude-ai-notifs/
#      enabled-terminals. Selecting kitty also enables its remote control.
#   7. Wires Stop plus event-native pending-input hooks in
#      ~/.claude/settings.json to the stable installed entrypoint (absolute
#      path), backing up the old file first and removing older forms.
#
# New-MacBook prerequisites this script checks for but does not install:
#   xcode-select --install         (swiftc, git)
#   brew install python@3.12       (python for the venv; or install uv)
# Everything else (say, afplay, osascript, curl) ships with macOS.

set -euo pipefail
umask 077

REPO="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.local/share/claude-ai-notifs"
SETUP_LOG_AFTER_INSTALL=""

setup_log_on() {
    mkdir -p "$BASE"
    chmod 700 "$BASE"
    touch "$BASE/debug" "$BASE/debug.log"
    chmod 600 "$BASE/debug" "$BASE/debug.log"
    printf '%s [setup] QA logging enabled\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
        >> "$BASE/debug.log"
    printf '==> QA logging enabled: %s\n' "$BASE/debug.log"
    printf '==> disable it with ./setup.sh --log-off (the log will be retained)\n'
}

setup_log_off() {
    if [ -d "$BASE" ]; then
        if [ -f "$BASE/debug.log" ]; then
            chmod 600 "$BASE/debug.log" 2>/dev/null || true
            printf '%s [setup] QA logging disabled\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
                >> "$BASE/debug.log"
        fi
        rm -f "$BASE/debug"
    fi
    printf '==> QA logging disabled; existing log retained at %s\n' "$BASE/debug.log"
    if [ -n "${CLAUDE_ANNOUNCE_DEBUG:-}" ]; then
        printf '==> warning: CLAUDE_ANNOUNCE_DEBUG is set and can still enable logging\n'
    fi
}

# Logging is a standalone setup action. On an existing install it toggles
# immediately without rebuilding anything; on a fresh --log-on invocation the
# platform installer runs normally and enables the trace only after success.
SETUP_LOG_ARG=""
for setup_arg in "$@"; do
    case "$setup_arg" in --log-on|--log-off) SETUP_LOG_ARG="$setup_arg" ;; esac
done
if [ -n "$SETUP_LOG_ARG" ] && [ "$#" -ne 1 ]; then
    printf 'error: --log-on and --log-off must be used by themselves\n' >&2
    exit 1
fi
case "${1:-}" in
    --log-off)
        setup_log_off
        exit 0
        ;;
    --log-on)
        if [ -x "$BASE/runtime/current/bin/claude-announce" ]; then
            setup_log_on
            exit 0
        fi
        SETUP_LOG_AFTER_INSTALL=1
        ;;
esac

# Keep one public entrypoint while letting each platform own its dependency and
# terminal integration. The existing macOS installer remains below unchanged.
case "$(uname -s)" in
    Linux)  exec "$REPO/setup-linux.sh" "$@" ;;
    Darwin) ;;
    *)      printf 'error: supported platforms are macOS and Linux\n' >&2; exit 1 ;;
esac

RELEASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

# Summarizer flags (env vars work too; flags win). Empty SUMMARIZER means the
# interactive picker in section 4 decides.
SUMMARIZER="${CLAUDE_ANNOUNCE_SUMMARIZER:-}"
MODEL="${CLAUDE_ANNOUNCE_OLLAMA_MODEL:-}"
REQUESTED_OLLAMA_HOST="${CLAUDE_ANNOUNCE_OLLAMA_HOST:-${OLLAMA_HOST:-}}"
ASSUME_YES=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
    arg="${args[$i]}"
    case "$arg" in
        --summarizer)   i=$((i + 1)); SUMMARIZER="${args[$i]:-}" ;;
        --summarizer=*) SUMMARIZER="${arg#--summarizer=}" ;;
        --model)        i=$((i + 1)); MODEL="${args[$i]:-}" ;;
        --model=*)      MODEL="${arg#--model=}" ;;
        --ollama-host)  i=$((i + 1)); REQUESTED_OLLAMA_HOST="${args[$i]:-}" ;;
        --ollama-host=*) REQUESTED_OLLAMA_HOST="${arg#--ollama-host=}" ;;
        --yes|-y)       ASSUME_YES=1 ;;
    esac
done
case "$SUMMARIZER" in ""|apple|ollama) ;; *)
    printf 'error: --summarizer must be "apple" or "ollama"\n' >&2; exit 1 ;;
esac

confirm() {
    local prompt="$1" reply
    [ -n "$ASSUME_YES" ] && return 0
    [ -r /dev/tty ] && [ -w /dev/tty ] || return 1
    printf '%s [y/N] ' "$prompt" > /dev/tty
    read -r reply < /dev/tty || reply=""
    case "$reply" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}
# Terminals the announcement runs in (one canonical key per line). The hook
# reads this and stays silent in terminals not listed here.
ENABLED_FILE="$BASE/enabled-terminals"
INSTALLED_ROOT="$BASE/runtime/current"
ANNOUNCE="$INSTALLED_ROOT/bin/claude-announce"

# Supported terminals, alphabetical by display name: "key|Display Name|bundle id".
# The picker lists only those actually installed.
SUPPORTED_TERMINALS=(
    "alacritty|Alacritty|org.alacritty"
    "ghostty|Ghostty|com.mitchellh.ghostty"
    "iterm2|iTerm2|com.googlecode.iterm2"
    "kitty|kitty|net.kovidgoyal.kitty"
    "terminal|Terminal|com.apple.Terminal"
    "wezterm|WezTerm|com.github.wez.wezterm"
)

info() { printf '==> %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

# Is a terminal (by bundle id) installed? Spotlight first, then well-known paths
# (Spotlight can be disabled or slow to index a fresh install).
terminal_installed() {
    # sed reads the full stream: grep -q can close after its first match,
    # SIGPIPE mdfind, and turn a real match into failure under pipefail.
    [ -n "$(mdfind "kMDItemCFBundleIdentifier == '$1'" 2>/dev/null | sed -n '1p')" ] \
        && return 0
    case "$1" in
        com.apple.Terminal)       [ -d "/System/Applications/Utilities/Terminal.app" ] ;;
        com.googlecode.iterm2)    [ -d "/Applications/iTerm.app" ] ;;
        com.mitchellh.ghostty)    [ -d "/Applications/Ghostty.app" ] ;;
        com.github.wez.wezterm)   [ -d "/Applications/WezTerm.app" ] ;;
        org.alacritty)            [ -d "/Applications/Alacritty.app" ] ;;
        net.kovidgoyal.kitty)     [ -d "/Applications/kitty.app" ] ;;
        *) return 1 ;;
    esac
}

# kitty needs remote control enabled for the hook to query which window is
# focused. Add it to kitty.conf idempotently (only if not already present).
enable_kitty_remote_control() {
    local conf="$HOME/.config/kitty/kitty.conf"
    mkdir -p "$(dirname "$conf")"
    [ -f "$conf" ] || : > "$conf"
    if grep -qE '^[[:space:]]*allow_remote_control[[:space:]]+(yes|socket-only|socket|password)' "$conf" 2>/dev/null; then
        info "  kitty: remote control already enabled ($conf)"
        return
    fi
    grep -q 'claude-ai-notifs' "$conf" 2>/dev/null && return
    {
        printf '\n# claude-ai-notifs: let the announcement hook ask kitty which window\n'
        printf '# is focused (per-tab detection). socket-only keeps it off the escape\n'
        printf '# channel; the hook reaches it via the inherited KITTY_LISTEN_ON.\n'
        printf 'allow_remote_control socket-only\n'
        printf 'listen_on unix:/tmp/kitty-{kitty_pid}\n'
    } >> "$conf"
    info "  kitty: enabled remote control in $conf (restart kitty to apply)"
}

# Present the installed supported terminals (alphabetical) and let the user pick
# which to enable. Idempotent: on re-run the current selection is pre-checked
# and can be extended. Writes ENABLED_FILE. $1 is an optional preselection
# (comma/space keys) for non-interactive use; empty means prompt.
choose_terminals() {
    local preselect="$1"
    local keys=() names=() entry key name bid idx k
    for entry in "${SUPPORTED_TERMINALS[@]}"; do
        IFS='|' read -r key name bid <<< "$entry"
        if terminal_installed "$bid"; then keys+=("$key"); names+=("$name"); fi
    done
    mkdir -p "$BASE"
    if [ "${#keys[@]}" -eq 0 ]; then
        info "no supported terminal detected; defaulting to Terminal.app"
        printf 'terminal\n' > "$ENABLED_FILE"
        return
    fi

    # Seed the selection: explicit preselection, else current file (re-run),
    # else all installed (first run default).
    local sel=" " p
    if [ -n "$preselect" ]; then
        for p in $(printf '%s' "$preselect" | tr ',' ' '); do sel="$sel$p "; done
    elif [ -f "$ENABLED_FILE" ]; then
        sel=" $(tr '\n' ' ' < "$ENABLED_FILE") "
    else
        for k in "${keys[@]}"; do sel="$sel$k "; done
    fi

    # Interactive toggle menu, unless a preselection was given or there is no tty.
    if [ -z "$preselect" ] && [ -e /dev/tty ]; then
        local line num i
        while true; do
            echo
            info "Enable spoken announcements in which terminals? (installed only)"
            i=1
            for idx in "${!keys[@]}"; do
                case "$sel" in *" ${keys[$idx]} "*) k="x";; *) k=" ";; esac
                printf '     %d) [%s] %s\n' "$i" "$k" "${names[$idx]}"
                i=$((i + 1))
            done
            printf '     toggle by number (e.g. "1 3"), or press Enter to confirm: '
            read -r line < /dev/tty || line=""
            [ -z "$line" ] && break
            for num in $line; do
                idx=$((num - 1))
                k="${keys[$idx]:-}"
                [ -n "$k" ] || continue
                case "$sel" in
                    *" $k "*) sel=$(printf '%s' "$sel" | sed "s/ $k / /") ;;
                    *)        sel="$sel$k " ;;
                esac
            done
        done
    fi

    # Write the enabled file (installed keys only, alphabetical) and run any
    # per-terminal setup for the chosen ones.
    : > "$ENABLED_FILE"
    local chosen=()
    for idx in "${!keys[@]}"; do
        k="${keys[$idx]}"
        case "$sel" in
            *" $k "*)
                printf '%s\n' "$k" >> "$ENABLED_FILE"
                chosen+=("${names[$idx]}")
                [ "$k" = kitty ] && enable_kitty_remote_control
                ;;
        esac
    done
    if [ "${#chosen[@]}" -gt 0 ]; then
        info "announcements enabled in: ${chosen[*]}"
    else
        info "no terminals selected - the hook will stay silent until you re-run and pick some"
    fi
}

# Catch-all for anything not individually guarded below: say what failed and
# that re-running is safe (every step is idempotent).
trap 'printf "error: setup failed while running: %s\nFix the issue above and re-run ./setup.sh - it is safe to re-run.\n" "$BASH_COMMAND" >&2' ERR

# --test: report the state of every component, then run one end-to-end
# announcement using the newest transcript, with focus checks bypassed so it
# always speaks.
if [ "${1:-}" = "--test" ]; then
    ok=1
    if [ -x "$BASE/venv/bin/python" ]; then
        info "kokoro venv: ok"
    else
        info "kokoro venv: MISSING - run ./setup.sh first"; ok=0
    fi
    for f in kokoro-v1.0.onnx voices-v1.0.bin; do
        if [ -s "$BASE/$f" ]; then
            info "$f: ok"
        else
            info "$f: MISSING - run ./setup.sh first"; ok=0
        fi
    done
    if [ -x "$BASE/bin/claude-announce-summarize" ]; then
        info "on-device summarizer: $("$BASE/bin/claude-announce-summarize" --check 2>/dev/null || true)"
    else
        info "on-device summarizer: not built (claude -p fallback will be used)"
    fi
    test_summarizer=$(head -n 1 "$BASE/summarizer" 2>/dev/null || true)
    if [ "$test_summarizer" = "ollama" ]; then
        test_host=$(head -n 1 "$BASE/ollama-host" 2>/dev/null || true)
        test_model=$(head -n 1 "$BASE/ollama-model" 2>/dev/null || true)
        info "summarizer choice: ollama ($test_model)"
        if [ -x "$BASE/venv/bin/python" ] && [ -n "$test_host" ] \
                && test_probe=$("$BASE/venv/bin/python" "$REPO/bin/claude-announce-ollama.py" probe "$test_host" 2>/dev/null); then
            info "Ollama: reachable (${test_probe#*$'\t'}) at ${test_probe%%$'\t'*}"
            if "$BASE/venv/bin/python" "$REPO/bin/claude-announce-ollama.py" has-model "$test_host" "$test_model" 2>/dev/null; then
                info "Ollama model: ok"
            else
                info "Ollama model: MISSING ($test_model) - announcements fall back to Apple/claude -p"
            fi
        else
            info "Ollama: UNREACHABLE at ${test_host:-unset} - announcements fall back to Apple/claude -p"
        fi
    else
        info "summarizer choice: ${test_summarizer:-apple (default)}"
    fi
    if command -v claude >/dev/null 2>&1; then
        info "claude CLI (fallback summarizer): ok"
    else
        info "claude CLI (fallback summarizer): not found"
    fi
    if [ -x "$BASE/bin/claude-announce-miccheck" ]; then
        info "meeting detection (mic in use): $("$BASE/bin/claude-announce-miccheck" 2>/dev/null || true)"
        info "  (BUSY means the announcement below arrives as a silent banner, not voice)"
    else
        info "meeting detection: not built (voice also plays during meetings)"
    fi
    if [ -x "$ANNOUNCE" ]; then
        info "self-contained runtime: ok ($INSTALLED_ROOT)"
    else
        info "self-contained runtime: MISSING - run ./setup.sh first"; ok=0
    fi
    if [ -f "$ENABLED_FILE" ]; then
        info "enabled terminals: $(tr '\n' ' ' < "$ENABLED_FILE")"
    else
        info "enabled terminals: (none recorded - announces in every terminal)"
    fi
    [ "$ok" = 1 ] || die "missing pieces above"
    # sed -n '1p' (not head -1) so it reads the whole stream: head closes the
    # pipe after one line, which SIGPIPEs sort (exit 141) and, under pipefail,
    # aborts setup once there are enough transcripts to fill sort's buffer.
    transcript=$(find "$HOME/.claude/projects" -name '*.jsonl' -not -path '*/memory/*' \
        -exec stat -f '%m %N' {} + 2>/dev/null | sort -rn | sed -n '1p' | cut -d' ' -f2-)
    [ -n "$transcript" ] || die "no Claude transcripts found under ~/.claude/projects (run a claude session first)"
    info "announcing most recent transcript: $transcript"
    printf '{"transcript_path": "%s"}' "$transcript" \
        | CLAUDE_ANNOUNCE_FORCE=1 "$ANNOUNCE" stop
    if [ -x "$BASE/bin/claude-announce-miccheck" ] \
            && "$BASE/bin/claude-announce-miccheck" >/dev/null 2>&1; then
        info "test done - the mic is in use, so this arrived as a silent banner notification."
    else
        info "test done - you should have heard a spoken sentence."
    fi
    info "heard/saw nothing? Check the output volume, notification settings, and that"
    info "Terminal is allowed under System Settings > Privacy & Security > Automation."
    exit 0
fi

# --uninstall: surgically remove the claude-announce entries from every managed
# hook event (other hooks untouched), then delete the runtime dir.
# Does not restore any backup: backups may predate unrelated settings changes.
if [ "${1:-}" = "--uninstall" ]; then
    exec "$REPO/bin/claude-announce-uninstall"
fi

# 1. Prerequisites -----------------------------------------------------------

[ "$(uname -m)" = "arm64" ] || die "Apple Silicon required (Kokoro and Apple Intelligence)"

osver=$(sw_vers -productVersion)
case "$osver" in
    2[6-9].*|[3-9][0-9].*) ;;
    *) info "macOS $osver: Apple Foundation Models need macOS 26+; the claude -p fallback will be used" ;;
esac

xcode-select -p >/dev/null 2>&1 || die "Xcode Command Line Tools missing: run  xcode-select --install"

# Python 3.12+ for the Kokoro venv (requirements.lock pins numpy 2.5.1, which
# requires >=3.12; 3.12 and 3.13 are both tested). Prefer uv (it can fetch a
# pinned Python), then a versioned brew python, then plain python3.
PYTHON=""
USE_UV=""
if command -v uv >/dev/null 2>&1; then
    USE_UV=1
else
    for cand in python3.12 python3.13 python3; do
        if command -v "$cand" >/dev/null 2>&1 \
           && "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)' 2>/dev/null; then
            PYTHON="$cand"
            break
        fi
    done
    [ -n "$PYTHON" ] || die "no Python 3.12+ found: run  brew install python@3.12  (or install uv)"
fi

# 2. Kokoro TTS venv + models ------------------------------------------------

mkdir -p "$BASE/bin"
chmod 700 "$BASE" "$BASE/bin"
cd "$BASE"

PIP_HINT="could not install the hash-locked dependencies. Most common cause: the
venv Python is older than 3.12 (requirements.lock pins numpy 2.5.1, which needs
>=3.12). Install Python 3.12 (brew install python@3.12), delete $BASE/venv, and
re-run."

# Recreate a venv left by an older install if its Python predates the lock's
# 3.12 floor; otherwise the --require-hashes install below fails on numpy.
if [ -x venv/bin/python ] \
   && ! venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)' 2>/dev/null; then
    info "existing venv uses Python < 3.12; recreating it"
    rm -rf venv
fi
if [ ! -x venv/bin/python ]; then
    info "creating venv"
    if [ -n "$USE_UV" ]; then
        uv venv venv --python 3.12 \
            || die "uv could not create the venv (it downloads Python 3.12, so this needs network); re-run once fixed"
    else
        "$PYTHON" -m venv venv \
            || die "could not create a venv with $PYTHON; try  brew install python@3.12  and re-run"
    fi
fi
# Install from the hash-locked requirements.lock (--require-hashes): every
# package, including the full transitive tree, is pinned to a SHA-256 so a
# tampered or substituted wheel is rejected. The lock is universal (spans the
# supported Python range); regenerate it with
#   uv pip compile requirements.txt --generate-hashes --universal -o requirements.lock
info "installing the hash-locked Kokoro venv (see requirements.lock)"
if [ -n "$USE_UV" ]; then
    uv pip install --quiet --python venv/bin/python --require-hashes -r "$REPO/requirements.lock" \
        || die "$PIP_HINT"
else
    venv/bin/pip install --quiet --upgrade pip || die "pip self-upgrade failed (network?); re-run once fixed"
    venv/bin/pip install --quiet --require-hashes -r "$REPO/requirements.lock" || die "$PIP_HINT"
fi

# Expected SHA-256 of each model file. These match the canonical kokoro-onnx
# model-files-v1.0 release (cross-checked against the leonelhs/kokoro-thewh1teagle
# Hugging Face mirror). Verifying the hash - not just that the file is nonempty -
# catches a truncated/corrupted download or a tampered mirror before the file is
# ever loaded.
model_sha256() {
    case "$1" in
        kokoro-v1.0.onnx) echo "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5" ;;
        voices-v1.0.bin)  echo "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d" ;;
    esac
}
verify_sha256() { [ "$(shasum -a 256 "$1" 2>/dev/null | awk '{print $1}')" = "$2" ]; }

for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    expected=$(model_sha256 "$f")
    if [ -s "$f" ] && verify_sha256 "$f" "$expected"; then
        continue                        # already present and intact
    fi
    [ -s "$f" ] && info "$f present but checksum mismatched; re-downloading"
    info "downloading $f (kokoro-v1.0.onnx is ~310 MB; this can take a few minutes)"
    curl -fL --retry 2 -# -o "$f.part" "$RELEASE/$f" \
        || die "download of $f failed (network or proxy issue?); re-run ./setup.sh to retry"
    [ -s "$f.part" ] || { rm -f "$f.part"; die "downloaded $f is empty; re-run ./setup.sh to retry"; }
    verify_sha256 "$f.part" "$expected" \
        || { rm -f "$f.part"; die "$f failed SHA-256 verification (expected $expected); re-run ./setup.sh to retry"; }
    mv "$f.part" "$f"
done

# 3. Apple Foundation Models summarizer --------------------------------------

AFM_OK=""
info "compiling claude-announce-summarize (Apple Foundation Models)"
if swiftc -O -parse-as-library "$REPO/src/claude-announce-summarize.swift" \
        -o "$BASE/bin/claude-announce-summarize" 2>/dev/null; then
    if avail=$("$BASE/bin/claude-announce-summarize" --check 2>/dev/null); then
        info "on-device model: $avail"
        AFM_OK=1
    else
        info "on-device model: ${avail:-unavailable}"
        info "enable it under System Settings > Apple Intelligence & Siri;"
        info "until then announcements fall back to  claude -p --model haiku"
    fi
else
    info "swiftc build failed (old CLT/SDK?); using the claude -p fallback only"
    rm -f "$BASE/bin/claude-announce-summarize"
fi

info "compiling claude-announce-miccheck (meeting detection)"
if swiftc -O "$REPO/src/claude-announce-miccheck.swift" \
        -o "$BASE/bin/claude-announce-miccheck" 2>/dev/null; then
    info "microphone state now: $("$BASE/bin/claude-announce-miccheck" 2>/dev/null || true)"
else
    info "miccheck build failed; the voice will also play during meetings"
    rm -f "$BASE/bin/claude-announce-miccheck"
fi

# 4. Summarizer selection ------------------------------------------------------
# Announcements can be summarized by the Apple on-device model (zero extra
# footprint, needs Apple Intelligence) or by a local Ollama model (measured
# more accurate on machines with the memory for a strong model; see CLAUDE.md).
# The choice lands in $BASE/summarizer and the runtime honors it; the Apple
# model and claude -p stay in the fallback chain either way, so a stopped
# Ollama only degrades an announcement, never drops it.

OLLAMA_HELPER="$REPO/bin/claude-announce-ollama.py"
HELPER_PY="$BASE/venv/bin/python"

# Default Ollama model by unified memory: a ~19 GB 30B MoE model needs real
# headroom; below 36 GiB the 4B model is the safe pick.
mem_gib=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))
if [ -z "$MODEL" ]; then
    if [ "$mem_gib" -ge 36 ]; then MODEL="qwen3-coder:30b"; else MODEL="qwen3.5:4b"; fi
fi
model_size_hint() {
    case "$1" in
        qwen3-coder:30b) printf '~19 GB download' ;;
        qwen3.5:4b)      printf '~2.5 GB download' ;;
        *)               printf 'size varies by model' ;;
    esac
}

RECORDED_SUMMARIZER=$(head -n 1 "$BASE/summarizer" 2>/dev/null || true)
if [ -z "$SUMMARIZER" ]; then
    # Interactive pick. Default: the recorded choice on a re-run, else Apple
    # when it is available, else Ollama (the alternative is the claude -p
    # fallback on every announcement).
    default_choice=1
    [ "$RECORDED_SUMMARIZER" = "ollama" ] && default_choice=2
    [ -z "$RECORDED_SUMMARIZER" ] && [ -z "$AFM_OK" ] && default_choice=2
    if [ -e /dev/tty ]; then
        echo
        info "Which summarizer should write the spoken announcements?"
        if [ -n "$AFM_OK" ]; then
            printf '     1) Apple on-device model (no downloads, near-zero memory)\n'
        else
            printf '     1) Apple on-device model (NOT available on this Mac; falls back to claude -p)\n'
        fi
        printf '     2) Ollama local model: %s (%s' "$MODEL" "$(model_size_hint "$MODEL")"
        [ "$mem_gib" -lt 16 ] && printf '; NOTE: %s GiB RAM is tight for local models' "$mem_gib"
        printf ')\n'
        printf '     choose 1 or 2, or press Enter for %s: ' "$default_choice"
        read -r summarizer_reply < /dev/tty || summarizer_reply=""
        case "${summarizer_reply:-$default_choice}" in
            2) SUMMARIZER="ollama" ;;
            *) SUMMARIZER="apple" ;;
        esac
    else
        SUMMARIZER="${RECORDED_SUMMARIZER:-apple}"
        [ "$SUMMARIZER" = "ollama" ] || SUMMARIZER="apple"
    fi
fi

probe_ollama() { "$HELPER_PY" "$OLLAMA_HELPER" probe "$1" 2>/dev/null; }
wait_for_ollama() {
    local host="$1" count=0 result
    while [ "$count" -lt 30 ]; do
        if result=$(probe_ollama "$host"); then printf '%s' "$result"; return 0; fi
        sleep 1
        count=$((count + 1))
    done
    return 1
}

if [ "$SUMMARIZER" = "ollama" ]; then
    OLLAMA_CANDIDATE="${REQUESTED_OLLAMA_HOST:-http://127.0.0.1:11434}"
    OLLAMA_PROBE=$(probe_ollama "$OLLAMA_CANDIDATE" || true)
    if [ -z "$OLLAMA_PROBE" ] && [ -n "$REQUESTED_OLLAMA_HOST" ]; then
        die "the explicitly configured Ollama endpoint is unreachable: $REQUESTED_OLLAMA_HOST"
    fi

    # API not reachable: start an existing install before offering a new one.
    if [ -z "$OLLAMA_PROBE" ]; then
        if command -v brew >/dev/null 2>&1 && brew list --formula ollama >/dev/null 2>&1; then
            info "starting the installed Homebrew Ollama service"
            brew services start ollama >/dev/null
        elif [ -d "/Applications/Ollama.app" ]; then
            info "launching the installed Ollama app"
            open -ga Ollama
        elif command -v ollama >/dev/null 2>&1; then
            die "found $(command -v ollama) but no service manager for it; run 'ollama serve' and re-run setup"
        else
            command -v brew >/dev/null 2>&1 \
                || die "Ollama is not installed and Homebrew was not found; install Ollama from https://ollama.com/download and re-run"
            info "Ollama is not installed. Homebrew would install the ollama formula"
            info "and run it as a background service (brew services start ollama)."
            confirm "Install Ollama with Homebrew now?" \
                || die "Ollama installation was declined; re-run and pick the Apple summarizer instead"
            brew install ollama
            brew services start ollama >/dev/null
        fi
        OLLAMA_PROBE=$(wait_for_ollama "$OLLAMA_CANDIDATE" || true)
        [ -n "$OLLAMA_PROBE" ] \
            || die "Ollama did not become reachable at $OLLAMA_CANDIDATE; start it and re-run setup"
    fi

    OLLAMA_URL=${OLLAMA_PROBE%%$'\t'*}
    OLLAMA_VERSION=${OLLAMA_PROBE#*$'\t'}
    info "Ollama API: $OLLAMA_URL (version $OLLAMA_VERSION)"

    if "$HELPER_PY" "$OLLAMA_HELPER" has-model "$OLLAMA_URL" "$MODEL"; then
        info "Ollama model: $MODEL already installed"
    else
        info "model $MODEL is missing ($(model_size_hint "$MODEL"))"
        confirm "Download the Ollama model now?" || die "model download was declined"
        "$HELPER_PY" "$OLLAMA_HELPER" pull "$OLLAMA_URL" "$MODEL"
        "$HELPER_PY" "$OLLAMA_HELPER" has-model "$OLLAMA_URL" "$MODEL" \
            || die "Ollama did not report $MODEL after the pull completed"
    fi

    # One tiny generation proves the model actually answers on this server
    # (a first load of a large model can take several seconds). Warn only:
    # the runtime falls back to Apple/claude -p until Ollama responds.
    if printf 'Reply with the single word ok.' \
            | "$HELPER_PY" "$OLLAMA_HELPER" generate "$OLLAMA_URL" "$MODEL" --timeout 120 >/dev/null 2>&1; then
        info "Ollama summarizer: verified ($MODEL responds)"
    else
        info "warning: $MODEL did not answer a test generation; announcements will"
        info "fall back to the Apple model / claude -p until Ollama responds"
    fi

    printf '%s\n' "$OLLAMA_URL" > "$BASE/ollama-host"
    printf '%s\n' "$MODEL" > "$BASE/ollama-model"
fi

printf '%s\n' "$SUMMARIZER" > "$BASE/summarizer"
if [ "$SUMMARIZER" = "ollama" ]; then
    info "summarizer: ollama ($MODEL)"
else
    info "summarizer: apple on-device model"
fi

# 5. Self-contained runtime --------------------------------------------------

info "installing self-contained runtime scripts"
INSTALLED_ROOT=$("$BASE/venv/bin/python" "$REPO/bin/claude-announce-install.py" \
    "$REPO" "$BASE") || die "could not install the runtime scripts"
ANNOUNCE="$INSTALLED_ROOT/bin/claude-announce"
[ -x "$ANNOUNCE" ] || die "installed entrypoint is missing: $ANNOUNCE"
info "runtime entrypoint: $ANNOUNCE"

# 6. Terminal selection ------------------------------------------------------

# Preselection for non-interactive installs: CLAUDE_ANNOUNCE_TERMINALS env var
# or  --terminals "ghostty,iterm2"  on the command line. Empty => interactive.
PRESELECT="${CLAUDE_ANNOUNCE_TERMINALS:-}"
for ((i = 1; i <= $#; i++)); do
    case "${!i}" in
        --terminals)   j=$((i + 1)); PRESELECT="${!j:-}" ;;
        --terminals=*) v="${!i}"; PRESELECT="${v#--terminals=}" ;;
    esac
done
choose_terminals "$PRESELECT"

# 7. Hook wiring --------------------------------------------------------------

info "wiring hooks into $SETTINGS"
WIRE_PY="${PYTHON:-python3}"
[ -n "$USE_UV" ] && WIRE_PY="$BASE/venv/bin/python"
"$WIRE_PY" "$INSTALLED_ROOT/bin/claude-announce-hooks.py" \
    wire "$INSTALLED_ROOT" "$SETTINGS" \
    || die "hook wiring failed; $SETTINGS was not modified"

[ -z "$SETUP_LOG_AFTER_INSTALL" ] || setup_log_on

info "done. Hooks apply to NEW claude sessions (running ones keep their old hook snapshot)."
info "the runtime is self-contained; this repo can now be moved or deleted."
info "smoke test:  ./setup.sh --test"
