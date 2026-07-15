#!/bin/bash
# Setup for claude-ai-notifs: spoken Claude Code announcements in supported
# macOS terminals. Idempotent; safe to re-run after pulling changes or to
# enable additional terminals later.
#
#   ./setup.sh              full setup: venv, models, summarizer, terminals, hooks
#   ./setup.sh --terminals "ghostty,iterm2"
#                           non-interactive terminal selection (keys, comma/space)
#   ./setup.sh --test       after setup: run one end-to-end spoken announcement
#                           against the most recent Claude transcript
#   ./setup.sh --uninstall  remove the hooks and the runtime dir; the repo
#                           itself can be deleted afterwards
#
# What it does:
#   1. Checks prerequisites (Apple Silicon, macOS 26, Xcode CLT, Python 3.10+).
#   2. Creates the Kokoro TTS venv and downloads the model files (~340 MB)
#      into ~/.local/share/claude-ai-notifs.
#   3. Compiles the Apple Foundation Models summarizer with swiftc and reports
#      whether Apple Intelligence is enabled.
#   4. Asks which installed terminals to announce in (multi-select; re-run to
#      add more) and records them in ~/.local/share/claude-ai-notifs/
#      enabled-terminals. Selecting kitty also enables its remote control.
#   5. Wires hooks.Stop and hooks.Notification in ~/.claude/settings.json to
#      bin/claude-announce (absolute path), backing up the old file first and
#      removing any older notify-unfocused.sh entry this supersedes.
#
# New-MacBook prerequisites this script checks for but does not install:
#   xcode-select --install         (swiftc, git)
#   brew install python@3.12       (python for the venv; or install uv)
# Everything else (say, afplay, osascript, curl) ships with macOS.

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.local/share/claude-ai-notifs"
RELEASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
# Terminals the announcement runs in (one canonical key per line). The hook
# reads this and stays silent in terminals not listed here.
ENABLED_FILE="$BASE/enabled-terminals"

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
    mdfind "kMDItemCFBundleIdentifier == '$1'" 2>/dev/null | grep -q . && return 0
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
    if [ -f "$ENABLED_FILE" ]; then
        info "enabled terminals: $(tr '\n' ' ' < "$ENABLED_FILE")"
    else
        info "enabled terminals: (none recorded - announces in every terminal)"
    fi
    [ "$ok" = 1 ] || die "missing pieces above"
    transcript=$(find "$HOME/.claude/projects" -name '*.jsonl' -not -path '*/memory/*' \
        -exec stat -f '%m %N' {} + 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    [ -n "$transcript" ] || die "no Claude transcripts found under ~/.claude/projects (run a claude session first)"
    info "announcing most recent transcript: $transcript"
    printf '{"transcript_path": "%s"}' "$transcript" \
        | CLAUDE_ANNOUNCE_FORCE=1 "$REPO/bin/claude-announce" stop
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

# --uninstall: surgically remove the claude-announce entries from hooks.Stop
# and hooks.Notification (other hooks untouched), then delete the runtime dir.
# Does not restore any backup: backups may predate unrelated settings changes.
if [ "${1:-}" = "--uninstall" ]; then
    if [ -f "$SETTINGS" ] && command -v python3 >/dev/null 2>&1; then
        python3 - "$SETTINGS" <<'PY'
import json, shutil, sys, time

path = sys.argv[1]
try:
    with open(path) as f:
        settings = json.load(f)
except ValueError as e:
    print("    " + path + " is not valid JSON (" + str(e) + ");")
    print("    remove the claude-announce entries from hooks.Stop/hooks.Notification manually")
    sys.exit(0)
hooks = settings.get("hooks", {})
changed = False
for event in ("Stop", "Notification"):
    entries = hooks.get(event)
    if not entries:
        continue
    kept = [e for e in entries if "claude-announce" not in json.dumps(e)]
    if len(kept) != len(entries):
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
if changed:
    backup = path + ".bak." + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("    removed claude-announce hooks (backup: " + backup + ")")
else:
    print("    no claude-announce hooks found in " + path)
PY
    fi
    rm -rf "$BASE"
    info "removed $BASE"
    info "uninstalled. Running claude sessions keep their hook snapshot until restarted."
    info "this repo directory can now be deleted."
    exit 0
fi

# 1. Prerequisites -----------------------------------------------------------

[ "$(uname -m)" = "arm64" ] || die "Apple Silicon required (Kokoro and Apple Intelligence)"

osver=$(sw_vers -productVersion)
case "$osver" in
    2[6-9].*|[3-9][0-9].*) ;;
    *) info "macOS $osver: Apple Foundation Models need macOS 26+; the claude -p fallback will be used" ;;
esac

xcode-select -p >/dev/null 2>&1 || die "Xcode Command Line Tools missing: run  xcode-select --install"

# Python 3.10+ for the Kokoro venv. Prefer uv (it can fetch a pinned Python),
# then a versioned brew python, then plain python3.
PYTHON=""
USE_UV=""
if command -v uv >/dev/null 2>&1; then
    USE_UV=1
else
    for cand in python3.12 python3.13 python3.11 python3; do
        if command -v "$cand" >/dev/null 2>&1 \
           && "$cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON="$cand"
            break
        fi
    done
    [ -n "$PYTHON" ] || die "no Python 3.10+ found: run  brew install python@3.12  (or install uv)"
fi

# 2. Kokoro TTS venv + models ------------------------------------------------

mkdir -p "$BASE/bin"
cd "$BASE"

PIP_HINT="could not install kokoro-onnx/soundfile. Most common cause: the
Python used is too new or too old for prebuilt onnxruntime wheels. Install
Python 3.12 (brew install python@3.12), delete $BASE/venv, and re-run."

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
info "installing kokoro-onnx + soundfile into the venv"
if [ -n "$USE_UV" ]; then
    uv pip install --quiet --python venv/bin/python kokoro-onnx soundfile \
        || die "$PIP_HINT"
else
    venv/bin/pip install --quiet --upgrade pip || die "pip self-upgrade failed (network?); re-run once fixed"
    venv/bin/pip install --quiet kokoro-onnx soundfile || die "$PIP_HINT"
fi

for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    if [ ! -s "$f" ]; then
        info "downloading $f (kokoro-v1.0.onnx is ~310 MB; this can take a few minutes)"
        curl -fL --retry 2 -# -o "$f.part" "$RELEASE/$f" \
            || die "download of $f failed (network or proxy issue?); re-run ./setup.sh to retry"
        [ -s "$f.part" ] || die "downloaded $f is empty; re-run ./setup.sh to retry"
        mv "$f.part" "$f"
    fi
done

# 3. Apple Foundation Models summarizer --------------------------------------

info "compiling claude-announce-summarize (Apple Foundation Models)"
if swiftc -O -parse-as-library "$REPO/src/claude-announce-summarize.swift" \
        -o "$BASE/bin/claude-announce-summarize" 2>/dev/null; then
    if avail=$("$BASE/bin/claude-announce-summarize" --check 2>/dev/null); then
        info "on-device model: $avail"
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

# 4. Terminal selection ------------------------------------------------------

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

# 5. Hook wiring --------------------------------------------------------------

info "wiring hooks into $SETTINGS"
WIRE_PY="${PYTHON:-python3}"
[ -n "$USE_UV" ] && WIRE_PY="$BASE/venv/bin/python"
"$WIRE_PY" - "$REPO" "$SETTINGS" <<'PY' || die "hook wiring failed; $SETTINGS was not modified"
import json, os, shutil, sys, time

repo, path = sys.argv[1], sys.argv[2]
announce = os.path.join(repo, "bin", "claude-announce")

if os.path.exists(path):
    try:
        with open(path) as f:
            settings = json.load(f)
    except ValueError as e:
        sys.exit("    " + path + " is not valid JSON (" + str(e) + "); fix it and re-run")
    backup = path + ".bak." + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup)
    print("    backup: " + backup)
else:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    settings = {}

hooks = settings.setdefault("hooks", {})

def keep(entry):
    """Drop entries this setup owns or supersedes (idempotent re-runs)."""
    blob = json.dumps(entry)
    return "claude-announce" not in blob and "notify-unfocused.sh" not in blob

stop = [e for e in hooks.get("Stop", []) if keep(e)]
stop.append({"hooks": [{"type": "command", "command": announce + " stop"}]})
hooks["Stop"] = stop

notif = [e for e in hooks.get("Notification", []) if keep(e)]
notif.append({
    "matcher": "permission_prompt|agent_needs_input|elicitation_dialog",
    "hooks": [{"type": "command", "command": announce + " notification"}],
})
hooks["Notification"] = notif

with open(path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print("    hooks.Stop and hooks.Notification now run " + announce)
PY

info "done. Hooks apply to NEW claude sessions (running ones keep their old hook snapshot)."
info "smoke test:  ./setup.sh --test"
