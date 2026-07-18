#!/usr/bin/env bash
# Linux/Wayland installer for foot. Idempotent and safe to re-run.

set -euo pipefail
umask 077

REPO="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.local/share/claude-ai-notifs"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
FOOT_CONFIG="${CLAUDE_ANNOUNCE_FOOT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/foot/foot.ini}"
RELEASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
LEGACY_BASE="${CLAUDE_ANNOUNCE_LEGACY_BASE:-$HOME/.local/share/claude-announce}"
OLLAMA_HELPER="$REPO/bin/claude-announce-ollama.py"
MODEL="${CLAUDE_ANNOUNCE_OLLAMA_MODEL:-llama3.2:3b}"
UV_VERSION="${CLAUDE_ANNOUNCE_UV_VERSION:-0.11.28}"
REQUESTED_OLLAMA_HOST="${CLAUDE_ANNOUNCE_OLLAMA_HOST:-${OLLAMA_HOST:-}}"

ASSUME_YES=""
NO_SUDO=""
DRY_RUN=""
FORCE_FOOT_CONFIG=""
LOG_AFTER_INSTALL=""
ACTION="install"

info() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: ./setup.sh [options]

  --test                 run an audible end-to-end test of an existing install
  --uninstall            remove hooks, foot adapter, and installed runtime
  --yes                  accept setup prompts (sudo may still ask for a password)
  --no-sudo              never perform privileged installation
  --dry-run              print the dependency plan without changing anything
  --log-on               enable private QA logging (install first if needed)
  --log-off              disable QA logging and retain the existing log
  --foot-config PATH     configure this foot.ini
  --force-foot-config    override an explicit desktop notification command
  --ollama-host URL      use this explicit Ollama API endpoint
  --model NAME           Ollama model to provision (default: llama3.2:3b)
EOF
}

args=("$@")
log_option_seen=""
for arg in "${args[@]}"; do
    case "$arg" in --log-on|--log-off) log_option_seen=1 ;; esac
done
[ -z "$log_option_seen" ] || [ "${#args[@]}" -eq 1 ] \
    || die "--log-on and --log-off must be used by themselves"

index=0
while [ "$index" -lt "${#args[@]}" ]; do
    arg="${args[$index]}"
    case "$arg" in
        --yes) ASSUME_YES=1 ;;
        --no-sudo) NO_SUDO=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --log-on) LOG_AFTER_INSTALL=1 ;;
        --log-off)
            [ "$ACTION" = "install" ] || die "choose only one setup action"
            ACTION="log_off"
            ;;
        --force-foot-config) FORCE_FOOT_CONFIG=1 ;;
        --foot-config)
            index=$((index + 1)); FOOT_CONFIG="${args[$index]:-}"
            [ -n "$FOOT_CONFIG" ] || die "--foot-config needs a path"
            ;;
        --foot-config=*) FOOT_CONFIG="${arg#--foot-config=}" ;;
        --ollama-host)
            index=$((index + 1)); REQUESTED_OLLAMA_HOST="${args[$index]:-}"
            [ -n "$REQUESTED_OLLAMA_HOST" ] || die "--ollama-host needs a URL"
            ;;
        --ollama-host=*) REQUESTED_OLLAMA_HOST="${arg#--ollama-host=}" ;;
        --model)
            index=$((index + 1)); MODEL="${args[$index]:-}"
            [ -n "$MODEL" ] || die "--model needs a model name"
            ;;
        --model=*) MODEL="${arg#--model=}" ;;
        --test)
            [ "$ACTION" = "install" ] || die "choose only one of --test and --uninstall"
            ACTION="test"
            ;;
        --uninstall)
            [ "$ACTION" = "install" ] || die "choose only one of --test and --uninstall"
            ACTION="uninstall"
            ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $arg" ;;
    esac
    index=$((index + 1))
done

# setup later changes directory to $BASE. Resolve user-provided relative paths
# against the directory from which setup was launched so re-runs and hook
# wiring never accidentally target a path under $BASE.
case "$FOOT_CONFIG" in
    /*) ;;
    *) FOOT_CONFIG="$PWD/$FOOT_CONFIG" ;;
esac
case "$SETTINGS" in
    /*) ;;
    *) SETTINGS="$PWD/$SETTINGS" ;;
esac
case "$FOOT_CONFIG$SETTINGS" in
    *$'\n'*|*$'\r'*) die "configuration paths cannot contain newlines" ;;
esac

trap 'printf "error: Linux setup failed while running: %s\nFix the issue above and re-run ./setup.sh; every completed step is idempotent.\n" "$BASH_COMMAND" >&2' ERR

if [ "$ACTION" = "uninstall" ]; then
    exec "$REPO/bin/claude-announce-uninstall"
fi

log_on() {
    mkdir -p "$BASE"
    chmod 700 "$BASE"
    touch "$BASE/debug" "$BASE/debug.log"
    chmod 600 "$BASE/debug" "$BASE/debug.log"
    printf '%s [setup] QA logging enabled\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
        >> "$BASE/debug.log"
    info "QA logging enabled: $BASE/debug.log"
    info "disable it with ./setup.sh --log-off (the log will be retained)"
}

log_off() {
    if [ -d "$BASE" ]; then
        if [ -f "$BASE/debug.log" ]; then
            chmod 600 "$BASE/debug.log" 2>/dev/null || true
            printf '%s [setup] QA logging disabled\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
                >> "$BASE/debug.log"
        fi
        rm -f "$BASE/debug"
    fi
    info "QA logging disabled; existing log retained at $BASE/debug.log"
    [ -z "${CLAUDE_ANNOUNCE_DEBUG:-}" ] \
        || info "warning: CLAUDE_ANNOUNCE_DEBUG is set and can still enable logging"
}

if [ "$ACTION" = "log_off" ]; then
    log_off
    exit 0
fi

if [ -n "$LOG_AFTER_INSTALL" ] \
    && [ -x "$BASE/runtime/current/bin/claude-announce" ]; then
    log_on
    exit 0
fi

confirm() {
    local prompt="$1" reply
    [ -n "$ASSUME_YES" ] && return 0
    [ -r /dev/tty ] && [ -w /dev/tty ] || return 1
    printf '%s [y/N] ' "$prompt" > /dev/tty
    read -r reply < /dev/tty || reply=""
    case "$reply" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

find_python() {
    local candidate
    for candidate in python3.14 python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)' 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

bootstrap_python() {
    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

detect_ollama_service() {
    command -v systemctl >/dev/null 2>&1 || return 1
    if systemctl --user cat ollama.service >/dev/null 2>&1; then
        printf 'user\n'
        return 0
    fi
    if systemctl cat ollama.service >/dev/null 2>&1; then
        printf 'system\n'
        return 0
    fi
    return 1
}

if [ "$ACTION" = "test" ]; then
    ANNOUNCE="$BASE/runtime/current/bin/claude-announce"
    ok=1
    if [ -x "$BASE/venv/bin/python" ]; then
        info "kokoro venv: ok"
    else
        info "kokoro venv: MISSING - run ./setup.sh first"; ok=0
    fi
    for file in kokoro-v1.0.onnx voices-v1.0.bin; do
        if [ -s "$BASE/$file" ]; then
            info "$file: ok"
        else
            info "$file: MISSING - run ./setup.sh first"; ok=0
        fi
    done
    BOOT_PY=$(bootstrap_python || true)
    if [ -n "$BOOT_PY" ] && [ -f "$BASE/ollama-host" ] && [ -f "$BASE/ollama-model" ]; then
        host=$(head -n 1 "$BASE/ollama-host")
        model=$(head -n 1 "$BASE/ollama-model")
        if probe=$($BOOT_PY "$BASE/runtime/current/bin/claude-announce-ollama.py" probe "$host" 2>/dev/null); then
            info "Ollama: reachable (${probe#*$'\t'}) at ${probe%%$'\t'*}"
            if "$BOOT_PY" "$BASE/runtime/current/bin/claude-announce-ollama.py" has-model "$host" "$model"; then
                info "Ollama model: $model"
            else
                info "Ollama model: MISSING ($model)"; ok=0
            fi
        else
            info "Ollama: UNREACHABLE at $host"; ok=0
        fi
    else
        info "Ollama configuration: MISSING"; ok=0
    fi
    if [ -x "$ANNOUNCE" ]; then
        info "self-contained runtime: ok"
    else
        info "self-contained runtime: MISSING"; ok=0
    fi
    if [ -f "$BASE/foot-config-path" ]; then
        info "foot config: $(head -n 1 "$BASE/foot-config-path")"
    else
        info "foot config record: MISSING"; ok=0
    fi
    [ "$ok" = 1 ] || die "missing pieces above"

    transcript=$(find "$HOME/.claude/projects" -name '*.jsonl' -not -path '*/memory/*' \
        -printf '%T@ %p\n' 2>/dev/null | sort -rn | sed -n '1p' | cut -d' ' -f2-)
    [ -n "$transcript" ] || die "no Claude transcripts found under ~/.claude/projects"
    info "announcing most recent transcript: $transcript"
    printf '{"transcript_path": "%s"}' "$transcript" \
        | CLAUDE_ANNOUNCE_FORCE=1 "$ANNOUNCE" stop
    info "test done; you should have heard a spoken sentence or received a meeting notification."
    exit 0
fi

[ "$(uname -s)" = "Linux" ] || die "setup-linux.sh only supports Linux"
case "${XDG_SESSION_TYPE:-wayland}" in
    wayland) ;;
    *) info "warning: foot support is designed and tested for Wayland; detected ${XDG_SESSION_TYPE:-unknown}" ;;
esac

# Distribution-aware package plan. Only commands that are actually missing are
# included. Ollama is handled separately because its official installer also
# selects architecture/GPU support and creates its service.
PKG_MANAGER=""
if command -v pacman >/dev/null 2>&1; then PKG_MANAGER=pacman
elif command -v apt-get >/dev/null 2>&1; then PKG_MANAGER=apt
elif command -v dnf >/dev/null 2>&1; then PKG_MANAGER=dnf
elif command -v zypper >/dev/null 2>&1; then PKG_MANAGER=zypper
fi

packages=()
missing_capabilities=()
add_package() {
    local wanted="$1" existing
    [ -n "$wanted" ] || return 0
    for existing in "${packages[@]}"; do [ "$existing" = "$wanted" ] && return 0; done
    packages+=("$wanted")
}

add_missing() {
    local capability="$1" package existing
    for existing in "${missing_capabilities[@]}"; do
        [ "$existing" = "$capability" ] && return 0
    done
    missing_capabilities+=("$capability")
    package=$(package_for "$capability")
    add_package "$package"
}

package_for() {
    local capability="$1"
    case "$PKG_MANAGER:$capability" in
        pacman:python) echo python ;; apt:python|dnf:python|zypper:python) echo python3 ;;
        pacman:curl|apt:curl|dnf:curl|zypper:curl) echo curl ;;
        pacman:coreutils|apt:coreutils|dnf:coreutils|zypper:coreutils) echo coreutils ;;
        pacman:flock|apt:flock|dnf:flock|zypper:flock) echo util-linux ;;
        pacman:notify) echo libnotify ;; apt:notify) echo libnotify-bin ;;
        dnf:notify) echo libnotify ;; zypper:notify) echo libnotify-tools ;;
        pacman:audio) echo libpulse ;; apt:audio|dnf:audio) echo pulseaudio-utils ;;
        zypper:audio) echo libpulse-tools ;;
        pacman:foot|apt:foot|dnf:foot|zypper:foot) echo foot ;;
    esac
}

command -v python3 >/dev/null 2>&1 || add_missing python
command -v curl >/dev/null 2>&1 || add_missing curl
command -v timeout >/dev/null 2>&1 || add_missing coreutils
command -v flock >/dev/null 2>&1 || add_missing flock
command -v notify-send >/dev/null 2>&1 || add_missing notify
if ! command -v paplay >/dev/null 2>&1 \
    && ! command -v pw-play >/dev/null 2>&1 \
    && ! command -v aplay >/dev/null 2>&1; then
    add_missing audio
fi
command -v pactl >/dev/null 2>&1 || add_missing audio
command -v foot >/dev/null 2>&1 || add_missing foot

PREFLIGHT_OLLAMA_HOST="${REQUESTED_OLLAMA_HOST:-http://127.0.0.1:11434}"
PREFLIGHT_OLLAMA=""
PREFLIGHT_OLLAMA_SERVICE=$(detect_ollama_service || true)
PREFLIGHT_PY=$(bootstrap_python || true)
if [ -n "$PREFLIGHT_PY" ]; then
    PREFLIGHT_OLLAMA=$(
        "$PREFLIGHT_PY" "$OLLAMA_HELPER" probe "$PREFLIGHT_OLLAMA_HOST" 2>/dev/null \
        || true
    )
fi

info "Linux preflight"
info "  session: ${XDG_SESSION_TYPE:-unknown}"
info "  foot config: $FOOT_CONFIG"
info "  Ollama model: $MODEL"
if [ -n "$PREFLIGHT_OLLAMA" ]; then
    info "  Ollama API: reachable at ${PREFLIGHT_OLLAMA%%$'\t'*} (version ${PREFLIGHT_OLLAMA#*$'\t'})"
elif [ -n "$REQUESTED_OLLAMA_HOST" ]; then
    info "  Ollama API: explicit endpoint is not currently reachable ($REQUESTED_OLLAMA_HOST)"
elif command -v ollama >/dev/null 2>&1; then
    info "  Ollama API: not reachable; binary found at $(command -v ollama)"
elif [ -n "$PREFLIGHT_OLLAMA_SERVICE" ]; then
    info "  Ollama API: not reachable; $PREFLIGHT_OLLAMA_SERVICE service is installed"
else
    info "  Ollama API and binary: not detected"
fi
if [ "${#packages[@]}" -gt 0 ]; then
    [ -n "$PKG_MANAGER" ] \
        || die "missing system commands and no supported package manager was detected"
    info "  missing system packages ($PKG_MANAGER): ${packages[*]}"
elif [ "${#missing_capabilities[@]}" -gt 0 ]; then
    die "missing capabilities (${missing_capabilities[*]}) and no package mapping is available for this system"
else
    info "  system packages: all required capabilities found"
fi

if [ -n "$DRY_RUN" ]; then
    DRY_PY=$(find_python || true)
    if ! command -v uv >/dev/null 2>&1 \
        && { [ -z "$DRY_PY" ] \
            || ! "$DRY_PY" -c 'import ensurepip, venv' >/dev/null 2>&1; }; then
        info "  Python runtime: setup would offer a private uv installation under $BASE/bin"
    fi
    if [ -z "$PREFLIGHT_OLLAMA" ] && [ -z "$REQUESTED_OLLAMA_HOST" ] \
        && ! command -v ollama >/dev/null 2>&1; then
        info "  Ollama: not detected; setup would offer the official installer"
    fi
    info "dry run complete; no files, packages, services, models, or settings were changed"
    exit 0
fi

run_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

authorize_sudo() {
    [ -z "$NO_SUDO" ] || die "privileged installation is disabled by --no-sudo"
    [ "$(id -u)" -eq 0 ] && return 0
    command -v sudo >/dev/null 2>&1 || die "sudo is required to install missing system packages"
    info "requesting sudo authorization for the displayed system changes"
    sudo -v
}

if [ "${#packages[@]}" -gt 0 ]; then
    [ -z "$NO_SUDO" ] \
        || die "missing system packages cannot be installed with --no-sudo: ${packages[*]}"
    confirm "Install the missing system packages shown above?" \
        || die "system package installation was declined"
    authorize_sudo
    case "$PKG_MANAGER" in
        pacman) run_root pacman -S --needed --noconfirm -- "${packages[@]}" ;;
        apt)
            run_root apt-get update
            run_root apt-get install -y -- "${packages[@]}"
            ;;
        dnf) run_root dnf install -y -- "${packages[@]}" ;;
        zypper) run_root zypper --non-interactive install -- "${packages[@]}" ;;
    esac
fi

BOOT_PY=$(bootstrap_python || true)
[ -n "$BOOT_PY" ] || die "python3 is still unavailable after dependency installation"

PYTHON=$(find_python || true)
USE_UV=""
UV_BIN=""
if command -v uv >/dev/null 2>&1; then
    USE_UV=1
    UV_BIN=$(command -v uv)
elif [ -z "$PYTHON" ] \
    || ! "$PYTHON" -c 'import ensurepip, venv' >/dev/null 2>&1; then
    if [ -n "$PYTHON" ]; then
        info "Python 3.12+ is present, but its venv/ensurepip support is unavailable."
    else
        info "Python 3.12+ is unavailable."
    fi
    info "uv can install a private Python 3.12"
    info "under your user account without changing the system Python."
    confirm "Download the official uv standalone installer?" \
        || die "Python 3.12+ or uv is required for Kokoro"
    mkdir -p "$BASE/bin"
    uv_installer=$(mktemp "${TMPDIR:-/tmp}/uv-install.XXXXXX")
    trap 'rm -f "$uv_installer"' EXIT
    curl -fsSL "https://astral.sh/uv/$UV_VERSION/install.sh" -o "$uv_installer"
    chmod 700 "$uv_installer"
    UV_UNMANAGED_INSTALL="$BASE/bin" sh "$uv_installer"
    rm -f "$uv_installer"
    trap - EXIT
    UV_BIN="$BASE/bin/uv"
    [ -x "$UV_BIN" ] || die "the uv installer did not create $UV_BIN"
    USE_UV=1
fi

probe_ollama() {
    "$BOOT_PY" "$OLLAMA_HELPER" probe "$1" 2>/dev/null
}

wait_for_ollama() {
    local host="$1" count=0 result
    while [ "$count" -lt 30 ]; do
        if result=$(probe_ollama "$host"); then
            printf '%s' "$result"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    return 1
}

start_existing_ollama() {
    local binary user_unit recorded_unit unit_binary
    binary=$(command -v ollama 2>/dev/null || true)
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl --user cat ollama.service >/dev/null 2>&1; then
            info "starting the existing user Ollama service"
            systemctl --user enable --now ollama.service
            return 0
        fi
        if systemctl cat ollama.service >/dev/null 2>&1; then
            confirm "Enable and start the existing system Ollama service?" \
                || die "Ollama service startup was declined"
            authorize_sudo
            run_root systemctl enable --now ollama.service
            return 0
        fi

        [ -n "$binary" ] || return 1
        # A systemctl binary can exist in containers and WSL sessions without
        # an active per-user manager. Do not write a unit that cannot be used.
        systemctl --user show-environment >/dev/null 2>&1 || return 1

        # A tarball/package may provide only the binary. Install a narrowly
        # scoped user service rather than launching an untracked background job.
        confirm "Create and start a user Ollama service for $binary?" \
            || die "Ollama is installed but no running server was approved"
        user_unit="$HOME/.config/systemd/user/claude-ai-notifs-ollama.service"
        recorded_unit=$(head -n 1 "$BASE/ollama-user-service" 2>/dev/null || true)
        if [ -e "$user_unit" ] && [ "$recorded_unit" != "$user_unit" ]; then
            die "$user_unit already exists and was not created by this setup"
        fi
        case "$binary" in *$'\n'*|*$'\r'*) die "Ollama executable path contains a newline" ;; esac
        unit_binary=${binary//\\/\\\\}
        unit_binary=${unit_binary//\"/\\\"}
        unit_binary=${unit_binary//%/%%}
        mkdir -p "$(dirname "$user_unit")"
        {
            printf '[Unit]\nDescription=Ollama for claude-ai-notifs\nAfter=network-online.target\n\n'
            printf '[Service]\nExecStart="%s" serve\nRestart=on-failure\nRestartSec=3\n\n' "$unit_binary"
            printf '[Install]\nWantedBy=default.target\n'
        } > "$user_unit"
        chmod 600 "$user_unit"
        systemctl --user daemon-reload
        systemctl --user enable --now claude-ai-notifs-ollama.service
        mkdir -p "$BASE"
        printf '%s\n' "$user_unit" > "$BASE/ollama-user-service"
        return 0
    fi
    return 1
}

OLLAMA_CANDIDATE="${REQUESTED_OLLAMA_HOST:-http://127.0.0.1:11434}"
OLLAMA_PROBE=$(probe_ollama "$OLLAMA_CANDIDATE" || true)
if [ -z "$OLLAMA_PROBE" ] && [ -n "$REQUESTED_OLLAMA_HOST" ]; then
    die "the explicitly configured Ollama endpoint is unreachable: $REQUESTED_OLLAMA_HOST"
fi

if [ -z "$OLLAMA_PROBE" ] \
    && { command -v ollama >/dev/null 2>&1 \
        || [ -n "$(detect_ollama_service || true)" ]; }; then
    info "Ollama is installed, but its API is not reachable"
    start_existing_ollama \
        || die "could not start Ollama automatically; start 'ollama serve' and re-run setup"
    OLLAMA_PROBE=$(wait_for_ollama "$OLLAMA_CANDIDATE" || true)
fi

if [ -z "$OLLAMA_PROBE" ]; then
    info "Ollama is not installed or reachable. The official installer may add"
    info "a system user, GPU runtime files, and an enabled system service."
    confirm "Download and run the official Ollama Linux installer?" \
        || die "Ollama installation was declined"
    authorize_sudo
    installer=$(mktemp "${TMPDIR:-/tmp}/ollama-install.XXXXXX")
    trap 'rm -f "$installer"' EXIT
    curl -fsSL https://ollama.com/install.sh -o "$installer"
    chmod 700 "$installer"
    sh "$installer"
    rm -f "$installer"
    trap - EXIT
    OLLAMA_PROBE=$(probe_ollama "$OLLAMA_CANDIDATE" || true)
    if [ -z "$OLLAMA_PROBE" ] \
        && { command -v ollama >/dev/null 2>&1 \
            || [ -n "$(detect_ollama_service || true)" ]; }; then
        start_existing_ollama || true
    fi
    OLLAMA_PROBE=$(wait_for_ollama "$OLLAMA_CANDIDATE" || true)
    [ -n "$OLLAMA_PROBE" ] \
        || die "Ollama installed but its API did not become reachable at $OLLAMA_CANDIDATE"
fi

OLLAMA_URL=${OLLAMA_PROBE%%$'\t'*}
OLLAMA_VERSION=${OLLAMA_PROBE#*$'\t'}
info "Ollama API: $OLLAMA_URL (version $OLLAMA_VERSION)"

if "$BOOT_PY" "$OLLAMA_HELPER" has-model "$OLLAMA_URL" "$MODEL"; then
    info "Ollama model: $MODEL already installed"
else
    if [ "$MODEL" = "llama3.2:3b" ]; then
        info "model $MODEL is missing (downloads about 2 GB)"
    else
        info "model $MODEL is missing"
    fi
    confirm "Download the Ollama model now?" || die "model download was declined"
    "$BOOT_PY" "$OLLAMA_HELPER" pull "$OLLAMA_URL" "$MODEL"
    "$BOOT_PY" "$OLLAMA_HELPER" has-model "$OLLAMA_URL" "$MODEL" \
        || die "Ollama did not report $MODEL after the pull completed"
fi

mkdir -p "$BASE/bin"
chmod 700 "$BASE" "$BASE/bin"
printf '%s\n' "$OLLAMA_URL" > "$BASE/ollama-host"
printf '%s\n' "$MODEL" > "$BASE/ollama-model"

# Kokoro venv and hash-verified model assets match the macOS installation.
cd "$BASE"
if [ -x venv/bin/python ] \
    && ! venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)' 2>/dev/null; then
    info "existing venv uses Python < 3.12; recreating it"
    rm -rf venv
fi
if [ ! -x venv/bin/python ]; then
    info "creating Kokoro venv"
    if [ -n "$USE_UV" ]; then
        "$UV_BIN" venv venv --python 3.12
    else
        "$PYTHON" -m venv venv
    fi
fi
info "installing the hash-locked Kokoro dependencies"
if [ -n "$USE_UV" ]; then
    "$UV_BIN" pip install --quiet --python venv/bin/python --require-hashes -r "$REPO/requirements.lock"
else
    venv/bin/pip install --quiet --require-hashes -r "$REPO/requirements.lock"
fi

model_sha256() {
    case "$1" in
        kokoro-v1.0.onnx) echo "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5" ;;
        voices-v1.0.bin) echo "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d" ;;
    esac
}
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    else shasum -a 256 "$1" | awk '{print $1}'
    fi
}
for file in kokoro-v1.0.onnx voices-v1.0.bin; do
    expected=$(model_sha256 "$file")
    legacy_file="$LEGACY_BASE/$file"
    if [ ! -e "$file" ] && [ -s "$legacy_file" ] \
        && [ "$(sha256_of "$legacy_file")" = "$expected" ]; then
        if ln "$legacy_file" "$file" 2>/dev/null; then
            info "reusing verified $file from the legacy install (hard linked)"
        else
            cp "$legacy_file" "$file"
            info "reusing verified $file from the legacy install (copied)"
        fi
    fi
    if [ -s "$file" ] && [ "$(sha256_of "$file")" = "$expected" ]; then continue; fi
    [ -s "$file" ] && info "$file checksum mismatched; re-downloading"
    info "downloading $file"
    curl -fL --retry 2 -# -o "$file.part" "$RELEASE/$file"
    [ "$(sha256_of "$file.part")" = "$expected" ] \
        || { rm -f "$file.part"; die "$file failed SHA-256 verification"; }
    mv "$file.part" "$file"
done

"$BOOT_PY" "$REPO/bin/claude-announce-ding.py" "$BASE/ding.wav"

info "installing the self-contained runtime"
INSTALLED_ROOT=$("$BASE/venv/bin/python" "$REPO/bin/claude-announce-install.py" "$REPO" "$BASE")
ANNOUNCE="$INSTALLED_ROOT/bin/claude-announce"
DISPATCHER="$INSTALLED_ROOT/bin/claude-announce-foot"
if [ ! -x "$ANNOUNCE" ] || [ ! -x "$DISPATCHER" ]; then
    die "installed runtime is incomplete"
fi

# Record the foot config path BEFORE modifying foot.ini: uninstall discovers
# the managed block only through this record, and restore on an untouched
# config is a no-op success, so recording intent first means an interruption
# between the two writes can never strand a block uninstall cannot find.
printf '%s\n' "$FOOT_CONFIG" > "$BASE/foot-config-path"
configure_args=(configure "$FOOT_CONFIG" "$DISPATCHER" --foot-binary "$(command -v foot)")
[ -n "$FORCE_FOOT_CONFIG" ] && configure_args+=(--force)
config_rc=0
"$BASE/venv/bin/python" "$INSTALLED_ROOT/bin/claude-announce-foot-config.py" \
    "${configure_args[@]}" || config_rc=$?
if [ "$config_rc" -eq 3 ]; then
    confirm "foot has custom desktop-notification settings. Preserve them underneath and let claude-ai-notifs override them?" \
        || die "foot configuration change was declined"
    "$BASE/venv/bin/python" "$INSTALLED_ROOT/bin/claude-announce-foot-config.py" \
        configure "$FOOT_CONFIG" "$DISPATCHER" --force --foot-binary "$(command -v foot)"
elif [ "$config_rc" -ne 0 ]; then
    die "could not configure foot"
fi
printf 'foot\n' > "$BASE/enabled-terminals"

info "wiring Claude Code hooks into $SETTINGS"
"$BASE/venv/bin/python" "$INSTALLED_ROOT/bin/claude-announce-hooks.py" \
    wire "$INSTALLED_ROOT" "$SETTINGS"

[ -z "$LOG_AFTER_INSTALL" ] || log_on

if [ -d "$LEGACY_BASE" ] || [ -x "$HOME/arch/bin/claude-announce" ]; then
    info "legacy Linux announcement files were detected and left in place"
    info "for any already-running Claude sessions that still hold the old hook snapshot."
    info "After restarting foot and confirming the new setup, you may retire $LEGACY_BASE"
    info "and the old announcement hook scripts. Keep claude-bell-play if you keep [bell]."
fi

info "done. Restart foot to load its notification adapter."
info "hooks apply to NEW Claude sessions; running sessions retain their old hook snapshot."
info "after restarting foot, run ./setup.sh --test from foot for an end-to-end test."
