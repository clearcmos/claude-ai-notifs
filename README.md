# claude-ai-notifs

Spoken AI notifications for Claude Code sessions in supported macOS terminals
and foot on Linux/Wayland.
When a Claude session finishes a turn or needs your input or permission while
you are looking at another tab, window, or app, a synthesized voice tells you
what happened ("Made changes to the failing authentication tests.") instead of
a plain ding. The voice never names Claude as the speaker: you already know who
is speaking, so every word is spent on what happened. Grounded topics such as
"Claude Code hooks" remain intact.

On macOS you pick which installed terminals it runs in. Linux currently enables
only foot. See the support matrix below.

Before you install, three things that shape the experience:

- **Linux uses foot.** Both [upstream foot](https://codeberg.org/dnkl/foot) and the tabbed
  [clearcmos/foot](https://github.com/clearcmos/foot) fork are supported on
  Wayland. foot itself makes the per-terminal focus decision, so no compositor
  extension or terminal patch is required.
- **Apple Silicon Mac.** Apple Silicon is required; macOS 26 is not. Setup asks
  whether summaries come from Apple's on-device model or a local Ollama model
  (re-run any time to switch). The on-device summarizer needs macOS 26 with
  Apple Intelligence enabled; the Ollama option suits machines with the memory
  for a strong local model and can be provisioned entirely by setup (Homebrew
  install, service start, model pull). Whatever is selected, unavailable
  backends fall through: Ollama to the on-device model to
  `claude -p --model haiku`, which uses your Claude plan (or API billing) and
  adds a few seconds per announcement.
- **Tab-level "are you looking at it?" detection varies by terminal.** Most
  supported terminals can tell whether the finishing session is the tab you are
  actually viewing, so the voice stays quiet when you are watching and speaks
  when you are elsewhere; some cannot expose that information. See the matrix.

This started as a macOS port of a personal Linux setup built around a patched
foot terminal. Linux support now uses foot's standard OSC 777 desktop
notification path, which provides the same focus ownership to both upstream
foot and the tabbed fork without depending on the fork's `${pty}` extension.

## How it works

1. Claude Code hooks run the self-contained installed entrypoint under
   `~/.local/share/claude-ai-notifs/runtime/current/bin/`: `Stop` for completed
   responses, `PreToolUse` for `AskUserQuestion`, `PermissionRequest` for tool
   approvals, and `Notification` for background-agent or MCP input requests.
2. It reads the terminal hosting the session from the environment; if that
   terminal is not one you enabled at install, it stays silent. Otherwise it
   decides, where the terminal supports it, whether you are looking at this
   session's tab: it climbs the process tree to the session's tty and asks the
   frontmost terminal - via AppleScript (Terminal.app, iTerm2, supported
   Ghostty builds) or the terminal's CLI (WezTerm, kitty) - whether that tty is
   the visible tab/pane. If you are looking at it, nothing plays. If exact
   session focus cannot be determined, it speaks rather than risk dropping an
   announcement. On Linux it queues a private tokenized item and writes an OSC
   777 notification to the originating pty. foot invokes the installed
   dispatcher only if that exact terminal object is unfocused. In the tabbed
   fork, each tab has its own terminal object, so this remains tab-accurate.
3. `bin/claude-announce-extract.py` pulls the last user prompt from the session
   transcript and prefers Stop's authoritative `last_assistant_message` for the
   reply. `bin/claude-announce-pending.py` reads pending-input details directly
   from each hook's authoritative event payload. This matters because Claude
   Code writes transcripts asynchronously: a visible `AskUserQuestion` dialog
   can exist before its assistant/tool entry reaches the JSONL file. The
   corresponding `PermissionRequest` for an `AskUserQuestion` is suppressed so
   that one question produces only one announcement.
4. For a completed response, the selected summarizer - a configured Ollama
   endpoint (Linux always, macOS when chosen at setup) or Apple's on-device
   foundation model (macOS default) - produces a constrained status,
   exact evidence quote,
   and extractive topic. It sees the latest user request for intent and topic
   context, including whether the reply is requested generated content. Local
   code verifies outcome evidence only against Claude's reply, while a topic may
   be grounded in either the latest request or reply. It requires explicit
   completed-action language before accepting `changed` and renders the spoken
   sentence from a fixed template. Thus an imperative request can improve the
   topic but can never prove its own completion. Unsupported claims become
   neutral "Worked on..." wording. Likewise, the `produced` status is accepted
   only when the latest request positively asks for generated or rewritten
   content; a question that merely discusses generation cannot establish that
   content was requested. If the selected model is unavailable, the remaining
   chain (Apple's on-device model on macOS, then `claude -p --model haiku`)
   produces the same assessment and passes through the same validator. Waiting/dependency replies and state recaps have distinct
   statuses, so a vague latest prompt can still produce a useful announcement
   grounded in concrete names, systems, or artifacts from the reply.
   Pending-input notices continue to use direct one-sentence summarization.
   Ollama keeps the selected model in memory for five minutes after each
   generation request; the model remains installed on disk until removed from
   Ollama separately.
5. Kokoro TTS with the af_heart voice synthesizes the sentence. macOS first
   plays the Kokoro WAV through `afplay`; if synthesis or playback fails, it
   falls back to the native `say` voice, then the Glass ding if `say` also
   fails. Linux hands the WAV to foot's unfocused-terminal dispatcher and uses
   `paplay`, `pw-play`, or `aplay`, with a built-in ding and desktop notification
   as its fallback. Playback is serialized across sessions so concurrent
   completions speak one after another.
6. The voice stays quiet while the microphone is in use. macOS 14.4+ uses
   CoreAudio; Linux checks non-monitor capture streams through `pactl`. When a
   meeting, dictation session, or recording is active, the same grounded summary
   arrives through the desktop notification system instead. Meeting apps such
   as Zoom, Meet, Teams, Webex, Slack, Discord, and FaceTime generally keep the
   capture stream open while muted, so muted calls remain quiet. Detection is
   repeated at playback time and fails open toward speaking if unavailable.

Every stage degrades: a failed completed-turn assessment becomes the always-true
"Finished responding" notification; a missing pending-input summary uses
the plain Glass ding (a generic banner in a meeting); and playback follows the
platform fallback chains above. The hook always exits 0,
so it can never fail a session, and setup wires it with `async: true`, so the
several seconds of summarizing, synthesizing, and playback run in the background
and never delay the next turn.

## Supported terminals

On macOS, `setup.sh` offers only the terminals actually installed; pick one or
more, and re-run any time to add more. Linux currently configures foot only.

| Terminal | Focus detection | Mechanism |
| --- | --- | --- |
| Terminal.app | tab-level | AppleScript |
| iTerm2 | tab-level | AppleScript |
| Ghostty | tab-level when its AppleScript API exposes `tty`; v1.3.1 and older always speak | AppleScript (`tty` property) |
| WezTerm | pane-level | `wezterm cli` |
| kitty | tab-level; needs remote control (setup enables it, restart kitty) | `kitty @ ls` |
| Alacritty | none - always speaks, even while you are viewing its window | unavailable (no focused-window query) |
| foot on Linux/Wayland | terminal-level upstream; tab-level in clearcmos/foot | OSC 777 with `inhibit-when-focused=yes` |

"tab-level" means the voice stays silent while you are looking at the session
and speaks when you are on another tab, window, or app. Where per-tab detection
is unavailable (Alacritty, or Ghostty on v1.3.1 and older), it speaks whenever
one of the managed hooks fires, even if you are watching the session.
Ghostty added the required `tty` property after v1.3.1
([PR #11922](https://github.com/ghostty-org/ghostty/pull/11922)). Until a stable
release includes it, use a tip build for tab-level detection. Focus queries
only run when that terminal is frontmost and (Terminal.app/iTerm2/Ghostty) may
trigger a one-time macOS Automation prompt to allow.

## Requirements

### Linux

- Wayland and upstream foot or the tabbed clearcmos/foot fork
- Python 3.12+ or `uv`
- Ollama, either local or at an explicitly configured endpoint
- `curl`, `flock`, `notify-send`, and one of `paplay`, `pw-play`, or `aplay`
- `pactl` for meeting detection (the runtime fails open if it later disappears)
- Claude Code CLI

`setup.sh` performs a read-only preflight first. If system packages are
missing, it prints the exact package plan, asks for approval, and then invokes
`sudo -v`; the script never reads or stores the password itself. pacman, apt,
dnf, and zypper are recognized. If Ollama's API is already reachable, including
through a user service, container, manual server, or explicit remote endpoint,
it is reused. Service-manager checks are diagnostics and startup helpers, not
the source of truth. If no API or binary is found, setup separately explains
and offers the official Ollama installer; if the selected model is missing, it
asks before pulling it. When Python 3.12 venv support is unavailable, setup can
install a pinned `uv` privately under the project data directory instead of
replacing the system Python.

### macOS

Ships with macOS: `osascript`, `afplay`, `say`, `curl`. Needed on a new
machine:

- Apple Silicon Mac
- Xcode Command Line Tools (`xcode-select --install`) for `swiftc`
- Python 3.12+ (`brew install python@3.12`) or `uv`, for the Kokoro venv
- Claude Code CLI (already present if you run Claude sessions)
- macOS 26+ with Apple Intelligence enabled in System Settings > Apple
  Intelligence & Siri (optional; without both, summaries fall back to
  `claude -p`)
- macOS 14.4+ for automatic microphone-use detection (optional; on older
  releases the voice can still play during meetings)

## Setup

```
./setup.sh          # platform preflight, models/runtime, terminal config, hooks
./setup.sh --test   # deliver a test announcement from the newest transcript
./setup.sh --log-on # enable the private QA trace
./setup.sh --log-off # disable tracing while retaining the log
```

macOS summarizer selection (interactive by default; flags skip the prompt):

```sh
./setup.sh --summarizer ollama             # summarize with a local Ollama model
./setup.sh --summarizer ollama --model qwen3-coder:30b
./setup.sh --summarizer apple              # back to the on-device model
```

Choosing Ollama provisions everything: a reachable API is reused, an installed
server is started (Homebrew service or Ollama.app), or setup offers
`brew install ollama`, then pulls the model after confirmation. The default
model follows unified memory: `qwen3-coder:30b` (~19 GB) on machines with
36 GiB or more, `qwen3.5:4b` (~2.5 GB) otherwise.

Linux-specific examples:

```sh
./setup.sh --dry-run                       # show every planned change
./setup.sh --foot-config ~/.config/foot/foot.ini
```

Both platforms accept `--ollama-host URL` and `--model NAME`; on macOS they
apply when the Ollama summarizer is selected.

On Linux, setup adds a clearly marked block to `foot.ini`, validates the result
with `foot --check-config`, and asks before overriding any explicit desktop
notification command/action template or disabled focus inhibition. The
dispatcher forwards ordinary foot notifications using the usual `notify-send`
arguments. Restart
foot after setup, then run `./setup.sh --test`; the test explicitly bypasses
focus suppression so it is audible from the current tab.

### Migrating the earlier Linux/BEL setup

You do not need to uninstall the `~/arch/bin/claude-announce` setup first.
The hook writer structurally replaces its old Stop and Notification entries,
while preserving unrelated hooks and a symlinked `~/.claude/settings.json`.
Likewise, the foot configurator preserves a symlinked `foot.ini`: it adds the
new desktop-notification adapter to the symlink target without removing the old
`[bell]` block. Existing model files under `~/.local/share/claude-announce` are
SHA-256-verified and hard-linked into the new installation when possible, so
they are not downloaded again and, when hard links are available, are not stored
twice.

The old files are deliberately not deleted during setup because already-running
Claude sessions retain their old hook snapshot. Restart foot, open a new Claude
session, and run `./setup.sh --test`. Once that works and the old sessions are
closed, `~/.local/share/claude-announce` and the old announcement scripts can be
retired. Keep the old `[bell]` block and `claude-bell-play` only if you still
want the Crazy Frog sound for unrelated terminal BELs.

On macOS, setup detects your installed terminals and asks which to announce in
(multi-select). The terminal keys are: `terminal`, `iterm2`, `ghostty`,
`wezterm`, `kitty`, `alacritty`. The test command requires at least one existing
Claude transcript; it speaks normally or sends a silent banner if the
microphone is in use.

```sh
./setup.sh --terminals "ghostty,iterm2"   # macOS non-interactive selection
```

Notes if you are not the author:

- Existing hooks in `~/.claude/settings.json` are preserved; setup only adds
  its own Stop, AskUserQuestion, PermissionRequest, and Notification entries
  (and re-runs replace those entries).
- The Kokoro models (~340 MB) are downloaded from the `thewh1teagle/kokoro-onnx`
  GitHub release and verified by SHA-256 against the known release hashes before
  use (a mismatch aborts and re-downloads); setup needs network for that and for
  the pip install. Python dependencies install from a hash-locked
  `requirements.lock` (`--require-hashes`, full transitive tree), generated from
  `requirements.txt`.
- On macOS, re-run any time to enable additional terminals (newly installed or
  previously skipped); the picker pre-checks your current selection. Selecting
  kitty adds `allow_remote_control` to your `kitty.conf` (restart kitty to
  apply).
- Setup copies all runtime scripts into an atomic, versioned release under
  `~/.local/share/claude-ai-notifs/runtime` and wires hooks to its stable
  `runtime/current` path. After setup finishes, the checkout can be moved or
  deleted without affecting notifications. Use a fresh checkout to update or
  reconfigure the installation later.
- See the support matrix above for per-terminal focus behavior, and the note at
  the top about the macOS 26 / Apple Intelligence summarizer fallback.

Re-runnable. Hook wiring backs up `~/.claude/settings.json` first and, if an
older `notify-unfocused.sh` Notification hook is present, replaces it (this
supersedes that approach). Hooks take effect in new Claude sessions, not
already-running ones.

The first focus query for Terminal.app, iTerm2, or Ghostty may trigger a macOS
Automation permission prompt to control that terminal via AppleScript; allow it
once.

## Layout

```
bin/claude-announce              hook entry point (stop | ask | permission | notification)
bin/claude-announce-pending.py   authoritative pending-input payload extraction
bin/claude-announce-foot         Linux OSC enqueue + foot notification dispatcher
bin/claude-announce-foot-config.py  atomic marked foot.ini configuration
bin/claude-announce-ollama.py    stdlib Ollama discovery/generate/pull client
bin/claude-announce-ding.py      built-in Linux fallback sound generator
bin/claude-announce-extract.py   transcript -> announcement material
bin/claude-announce-render.py    grounded assessment -> conservative sentence
bin/claude-announce-focus.py     WezTerm/kitty focus-response parser
bin/claude-announce-hooks.py     settings.json wiring (wire | unwire)
bin/claude-announce-install.py   atomic self-contained runtime installer
bin/claude-announce-tts.py       Kokoro synthesis (runs in the venv)
bin/claude-announce-uninstall    standalone installed uninstaller
src/claude-announce-summarize.swift  Apple Foundation Models CLI
src/claude-announce-miccheck.swift   CoreAudio microphone-use detector
setup.sh                         installer / smoke test
setup-linux.sh                   Linux preflight and foot/Ollama setup
requirements.txt                 direct Kokoro deps (source for the lock)
requirements.lock                hash-locked full dependency tree (installed)
tests/                           unit, focus, config, and concurrency tests
```

Run the automated tests with:

```sh
python3 -m unittest discover -s tests   # stdlib only; no install needed
bash tests/test_terminal.sh             # host-terminal detection
bash tests/test_temp.sh                 # private temporary WAV lifecycle
bash tests/test_lock.sh                 # audio-lock concurrency
bash tests/test_playback.sh             # macOS playback fallback chain
```

They cover the transcript extractor (turn scoping, anti-hallucination,
authoritative final-reply fallback, slash-command, and notification logic),
authoritative pending-input payload extraction and duplicate-question
suppression, the grounded renderer (verbatim evidence, conservative status
validation, the generated-content request gate, neutral fallback, and
investigation-versus-completion regressions),
atomic runtime installation (source-checkout independence, safe upgrades, and
standalone uninstall),
settings.json hook wiring (structural
matching, idempotence, migration, uninstall, and atomic writes), WezTerm/kitty
focus parsing, host-terminal precedence, direct dependency source/lock
consistency, private TTS output, macOS playback fallbacks, and audio-lock
serialization and kill-release behavior. Linux coverage includes atomic foot
configuration, tokenized OSC delivery and ordinary-notification forwarding,
Ollama endpoint and generation behavior, the installed hook end to end,
read-only setup preflight, and the public QA logging toggle. CI runs
bash syntax checks, Python compilation, and the unit tests on Linux and macOS
for pull requests and pushes to `main`. The lock test exercises `lockf` on
macOS and self-skips where it is unavailable; ShellCheck runs once on Linux,
and the hash-locked dependency install is tested on both platforms. CI builds and
launches both Swift helpers' diagnostics on macOS; live Foundation Models
inference remains locally verified because it requires macOS 26 with Apple
Intelligence enabled.

Runtime artifacts live in `~/.local/share/claude-ai-notifs`: the venv, models,
compiled helpers, `enabled-terminals`, and versioned runtime script releases.
The hooks use an absolute path to the atomically updated `runtime/current`
installation, not the source checkout. Setup and the runtime use owner-only
permissions for newly created artifacts, and synthesized audio lives in a
securely randomized private temporary directory that is removed on exit.

## Troubleshooting

For temporary QA, enable the decision trace through setup and reproduce the
announcement:

```sh
./setup.sh --log-on
# ...run a Claude session in the terminal in question...
tail -f ~/.local/share/claude-ai-notifs/debug.log
./setup.sh --log-off
```

On an existing installation these commands only toggle logging; they do not
reinstall anything and take effect for the next hook invocation, including in
already-running Claude sessions. On a fresh machine, `--log-on` performs normal
setup and enables logging after installation succeeds. `--log-off` retains the
log for review. The file and its flag are owner-only, under
`~/.local/share/claude-ai-notifs`; the trace includes the exact spoken summary
and may therefore contain transcript-derived information. The log rotates to
`debug.log.1` once it exceeds 1 MiB, so an always-on toggle stays bounded.
Delete `debug.log` manually when the QA record is no longer needed.
`CLAUDE_ANNOUNCE_DEBUG=1` remains an environment-level override.

The log shows the host terminal, gate/focus decisions on macOS, Linux foot queue
and dispatch decisions, task and summary lengths, the summarizer used, and the
final action. A one-off ding can be a model cold start; it should warm up after
that call.

## Uninstall

```
./setup.sh --uninstall
```

If you already deleted the checkout, run the installed uninstaller instead:

```sh
~/.local/share/claude-ai-notifs/runtime/current/bin/claude-announce-uninstall
```

Removes the `claude-announce` entries from `hooks.Stop`, `hooks.PreToolUse`,
`hooks.PermissionRequest`, and `hooks.Notification` in
`~/.claude/settings.json` (other hooks and settings untouched, with a backup
written first) and deletes
`~/.local/share/claude-ai-notifs` (including the `enabled-terminals` list).
On Linux it first removes only the marked foot configuration block and removes
an Ollama user service only if this installer created that exact unit. Ollama is
treated as a shared system tool and is not uninstalled, even if setup originally
offered its official installer; pre-existing Ollama services are never removed.
The checkout is never removed and may already be gone. Already-running Claude
sessions keep their hook snapshot until restarted. If you enabled kitty, the `allow_remote_control`
block added to your `kitty.conf` is left in place; remove it manually if you
want.

If `settings.json` is not valid JSON (or both the installed venv and `python3`
are unavailable), uninstall
cannot edit it safely. Rather than report a clean uninstall it did not perform,
it leaves the installed runtime in place because the live hooks still point
there, warns you to delete every hook entry whose command is
`claude-announce` by hand, and exits nonzero.
