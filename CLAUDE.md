# CLAUDE.md

Spoken announcements for Claude Code sessions in supported macOS terminals
(Terminal.app, iTerm2, Ghostty, WezTerm, kitty, Alacritty). See README.md for
the user-facing overview; this file records what matters when changing the code.

## Provenance

Port of a sibling Linux setup: claude-announce there uses Ollama
(llama3.2:3b) + Kokoro + a pty BEL, and a patched foot terminal plays the
per-pty wav from its `[bell]` command only when the ringing tab is unfocused.

`bin/claude-announce-extract.py` is shared verbatim with that Linux setup
(it lives in its `bin/` too). Keep the two copies identical so both machines
announce the same things.

## Architecture decisions

- No terminal fork on macOS. foot owned focus logic on Linux (bell command
  only ran for unfocused tabs); here the hook climbs the process tree to the
  session tty and queries the frontmost supported terminal via AppleScript or
  its CLI, checking focus before doing work, before playback, and again after
  acquiring the audio lock.
- Summarizer is Apple's on-device foundation model (FoundationModels
  framework, macOS 26+, Apple Intelligence must be enabled), replacing Ollama.
  Fallback chain: on-device model -> `claude -p --model haiku` (guarded
  against hook recursion via CLAUDE_ANNOUNCE_INNER) -> deterministic neutral
  sentence for Stop, or plain ding for a pending-input notice.
- Pending-input summarization keeps the full instruction in the prompt with a
  "One-sentence announcement:" trailer. Tested: putting that entire formatting
  instruction in `LanguageModelSession(instructions:)` makes the small on-device
  model echo the reply verbatim. Stop announcements instead put only the short,
  critical no-overclaim invariant in session instructions; the prompt requests
  a constrained status/evidence/topic assessment.
- Compile the Swift CLI with `-parse-as-library` (single-file swiftc builds
  treat the file as main.swift, which rejects `@main`).
- TTS is kokoro-onnx with the af_heart voice, matching Linux. Degrades to
  native `say` when the venv or models are missing.
- macOS has no `timeout` binary; `with_timeout` in bin/claude-announce uses
  Homebrew coreutils `timeout` when present, else a kill-after-sleep watchdog.
- Meeting suppression is microphone-capture detection, not per-app logic:
  claude-announce-miccheck (CoreAudio process-object API, macOS 14.4+,
  kAudioProcessPropertyIsRunningInput) prints BUSY plus the capturing bundle
  ids. One signal covers Zoom/Meet/Teams/Webex/Slack huddles, muted included
  (meeting apps keep the capture stream open while muted). In-meeting delivery
  is a silent banner (osascript display notification) carrying the same
  summary; ding-path failures become a generic banner. A missing or failing
  miccheck fails toward the voice so announcements are never silently lost.
- Anti-hallucination (2026-07-14, after a real miss): the reply is the last
  contiguous run of assistant text WITHIN the current turn (after the last
  real user prompt), not just text after the last user-type entry - turns can
  end with tool calls, which made the reply empty and the summarizer invent
  outcomes from the request (a docs-sync job that was only being asked about
  was announced as fixed). When the turn has no reply text at all, the task
  carries a neutral "none recorded" note plus the final tool action, and the
  instruction forbids inferring outcomes from the request. The sibling Linux
  setup calls the same claude-announce-extract.py; keep the copies identical.
- Grounded Stop announcements (2026-07-16): a Stop hook means the response
  ended, not that the requested operation completed. The classifier sees the
  latest user request for interaction type/topic context and the reply for
  outcome evidence; it does not use earlier conversation turns. The Swift
  helper uses DynamicGenerationSchema (not @Generable macros: command-line
  Swift SDKs may omit the macro plugin) to return status + exact evidence + an
  extractive topic with greedy sampling. claude-announce-render.py verifies
  evidence only against the reply and topic against either the latest request
  or reply (ordered ellipsis-separated evidence and reordered already-present
  topic words are allowed), requires explicit
  completed-action grammar for `changed`, guards negative statuses and explicit
  negations, and renders a fixed template;
  unsupported claims downgrade to neutral "worked on" wording. Requested
  generated or rewritten content uses the separate `produced` status so a poem
  is not mislabeled as an explanation. `waiting` covers progress dependent on
  a future event/person/action, and `recapped` covers state/open-item summaries;
  their topics prefer concrete names, systems, projects, artifacts, or
  identifiers from the reply when the latest request is vague. Generic model
  topics (`request`, `task`, `issue`, `work`, `response`, `reply`) use truthful
  status-specific fallbacks instead. Haiku fallback
  produces the same JSON and passes through the same validator. With no recorded
  reply the status is forcibly neutral, and total model failure becomes the
  always-true "Claude finished responding" rather than an invented outcome.
  Modern hook replies are read directly from last_assistant_message and bounded
  with a head+tail slice so long replies retain their concluding qualifications;
  the shared extractor remains the compatibility fallback.
- Playback is serialized (2026-07-14): two sessions finishing at once used to
  talk over each other. audio_lock/audio_unlock in bin/claude-announce hold an
  exclusive macOS lockf(1) lock on an inherited fd (`exec 9>$BASE/audio.lock`;
  `lockf -s -t 180 9`) for the length of playback. This replaced an earlier
  mkdir+PID mutex (rewritten 2026-07-15): lockf uses the macOS fd form
  `lockf [-s] [-t seconds] fd` - verified in the man page and functionally, it
  locks the fd with no wrapped command and holds it for the shell's lifetime.
  The kernel arbitrates, so there is NO pid file, no stale-lock reclamation, and
  no compare-then-delete race - and a dead holder's lock releases automatically
  when the fd closes (proved in tests/test_lock.sh: concurrent workers serialize;
  a kill -9'd holder's lock frees immediately). The lock lives under $BASE (not
  world-writable /tmp; $HOME is constant across login/SSH/GUI contexts so all
  the user's sessions still share it). Both the main afplay/say path and the ding
  fallback take it; the focus/meeting state is re-checked after acquiring it (the
  wait may have been long); playback is with_timeout-bounded so a hold is only
  seconds; an EXIT trap closes the fd on every exit path. If lockf or $BASE is
  missing, or the 180s wait times out, audio_lock falls through to unserialized
  playback rather than dropping the announcement. NOTE the fd is inherited by
  playback children, so the lock is genuinely held across the whole afplay/say,
  not just the parent shell.
- Multi-terminal support (2026-07-15): focus detection is a dispatch keyed on
  the frontmost app's bundle id (front_bundle_id via lsappinfo). Each branch
  answers "is the frontmost terminal's active tab THIS session's tty":
  Terminal.app/iTerm2/Ghostty via AppleScript (`tty of ...`; iTerm2's scripting
  name is "iTerm", NOT "iTerm2"; Ghostty exposes `tty`/`pid` only on builds
  newer than v1.3.1 - older ones return empty and fall through to speak);
  WezTerm via `wezterm cli list-clients` (focused_pane_id) matched to the pane
  from `wezterm cli list` (tty_name) or $WEZTERM_PANE; kitty via `kitty @ ls`
  (focused window id vs the inherited $KITTY_WINDOW_ID), which needs
  allow_remote_control. Their JSON responses are parsed by the stdlib-only
  claude-announce-focus.py so the behavior is fixture-testable. Alacritty has
  no per-session API (verified: no sdef, IPC is create-window/config/get-config
  only) so it always speaks. Every branch fails open (speak) on any uncertainty
  - announcements are never dropped.
- Runtime privacy: setup and the hook use `umask 077`; setup also tightens $BASE
  and its bin directory to mode 0700. Existing debug logs are tightened to 0600
  before append, and the TTS helper independently uses umask 077. Kokoro writes
  `announcement.wav` inside a `mktemp -d` private directory rather than using a
  predictable PID filename, and an EXIT trap removes the directory on normal
  and catchable termination paths. This matters when an SSH context lacks
  macOS's per-user $TMPDIR and falls back to shared /tmp. Settings writes use a
  random 0600 sibling from tempfile.mkstemp before atomic os.replace.
- Per-terminal opt-in + gating (2026-07-15): setup.sh writes the chosen
  terminals to $BASE/enabled-terminals (canonical keys: terminal, iterm2,
  ghostty, wezterm, kitty, alacritty). The hook derives its host terminal from
  the inherited env (host_terminal) and exits silently unless that terminal is
  listed. host_terminal checks terminal-specific vars (KITTY_WINDOW_ID,
  WEZTERM_PANE, GHOSTTY_*, ALACRITTY_*, ITERM_SESSION_ID) BEFORE $TERM_PROGRAM,
  because $TERM_PROGRAM is inherited-stale in nested launches (kitty launched
  from a Terminal.app shell keeps TERM_PROGRAM=Apple_Terminal - it only sets
  KITTY_WINDOW_ID/TERM=xterm-kitty). A missing enabled-terminals file means a
  pre-feature install: announce everywhere (backward compatible). Unknown host
  => silent (only speak where opted in).
- setup.sh terminal picker: lists only installed terminals (mdfind by bundle id
  + path fallback), alphabetical, bash 3.2-safe multi-select toggle (macOS
  /bin/bash is 3.2 - no associative arrays; selection is a space-delimited
  string). The mdfind presence check consumes its full stream rather than using
  grep -q, which can SIGPIPE the producer and become a false negative under
  pipefail. Idempotent: re-run pre-checks the current selection and can add
  more. Non-interactive via `--terminals "a,b"` or
  $CLAUDE_ANNOUNCE_TERMINALS.
  Selecting kitty appends allow_remote_control (socket-only) + listen_on to
  kitty.conf, idempotently.

## Deployment

`setup.sh` is idempotent: venv + model downloads + swiftc build into
`~/.local/share/claude-ai-notifs`, then an atomic self-contained runtime install,
then the terminal picker (writes
`enabled-terminals`, configures kitty if chosen), then wires `hooks.Stop` and
`hooks.Notification` in `~/.claude/settings.json`. `setup.sh --test` delivers
one announcement from the newest transcript with both the focus check and the
terminal gate bypassed (CLAUDE_ANNOUNCE_FORCE=1 skips both); an active mic turns
that test into the same silent banner used at runtime.

Self-contained runtime (2026-07-16): setup copies every runtime shell/Python
file into `$BASE/runtime/releases/<unique>/bin`, then atomically replaces the
relative `$BASE/runtime/current` symlink with Python `os.replace`. Hooks target
the stable absolute `current/bin/claude-announce` path, so the checkout can be
moved/deleted and an interrupted upgrade cannot expose a partial file set. Old
tiny releases are retained so a hook already executing from one is never broken
mid-turn. The installed `claude-announce-uninstall` plus hooks helper allow clean
uninstall after the checkout is gone. `test_install.py` deletes a fake checkout
and proves render/uninstall still work, proves failed upgrades retain `current`,
and proves successful upgrades atomically select a new release.

Hook shape: the wired entries use Claude Code's exec form
(`command`+`args:["stop"]`) with `async:true`. Exec form runs the executable
directly with no shell tokenization, so the installed path needs no
quoting; async keeps the several-second announcement off the session's critical
path (command hooks block by default - confirmed against
code.claude.com/docs/en/hooks). The settings mutation lives in
`bin/claude-announce-hooks.py` (`wire`/`unwire`), NOT a shell heredoc, so it is
unit-testable. It matches our hooks structurally on each hook's command field -
never a substring of the whole entry, so an unrelated hook that merely mentions
the name is left alone. Getting the executable path out of the command is
form-aware: exec form's `command` is the OPAQUE path (an `args` array is
present), so it is used whole - splitting it on spaces was a real bug that made
uninstall miss a spaced executable path and strand the live hook; shell form's path is
the first shlex token. Match keys: exact announce path (when known), that
executable basename == claude-announce (catches legacy repo installs), or the legacy
notify-unfocused.sh. Writes are atomic (temp sibling + os.replace, mode
preserved) so a crash cannot truncate the user's settings.json, and backups
carry a pid suffix so same-second re-runs do not collide.

Supply chain: the venv installs from the hash-locked `requirements.lock`
(`--require-hashes`: full transitive tree, SHA-256 per artifact), generated from
the human-edited `requirements.txt` via
`uv pip compile requirements.txt --generate-hashes --universal` (universal so it
spans the supported Python range on both install paths). The lock's numpy 2.5.1
requires Python >=3.12, so 3.12 is the hard floor (3.12-3.14 tested): setup
detects >=3.12, and recreates a leftover venv built on an older Python before
installing (else the --require-hashes install fails on numpy). CI has a
macOS-only step that builds a venv, installs the lock with --require-hashes, and
imports the runtime deps, so a lock/floor mismatch is caught. A stdlib unit test
also compares every exact direct pin in requirements.txt with requirements.lock,
so a source-only dependency bump cannot merge behind a green build. After
editing a pin, regenerate the lock and re-test. Separately, each Kokoro model
file is SHA-256-verified against the canonical release hash before use -
present-but-wrong or truncated files are re-downloaded, and a post-download
mismatch aborts. Those hashes are hard-coded in setup.sh's `model_sha256`; if the
upstream release ever re-cuts the model files, update the hash there.

`--uninstall` never reports a clean removal it did not perform: on success it
removes the hooks (atomically) and deletes $BASE; if settings.json is invalid
JSON or both the installed venv and python3 are missing it leaves $BASE in place
(the live hooks still point there), warns to remove the entries by hand, and
exits nonzero. The standalone installed uninstaller has the same behavior.

Tests: `test_extract.py` exercises claude-announce-extract.py (turn scoping, the
Stop hook's authoritative last_assistant_message with transcript fallback, the
"none recorded" anti-hallucination path, slash commands, notification asks);
`test_grounding.py` exercises assessment parsing, verbatim grounding,
status-specific evidence gates, and investigation-versus-change regressions;
`test_hooks.py` exercises claude-announce-hooks.py (structural matching including
spaced exec paths, idempotence, legacy migration, uninstall, atomic write);
`test_install.py` exercises the atomic versioned runtime, repo independence,
failed-upgrade rollback, permissions, and installed standalone uninstall;
`test_focus.py` covers WezTerm/kitty focus parsing; `test_requirements.py` guards
direct-pin lock drift; `test_tts.py` verifies the Kokoro adapter and its private
output mode with fake runtime modules. These are stdlib unittest, loading
hyphenated targets by path so extract.py stays byte-identical to the Linux copy. `test_terminal.sh`
tests host-terminal detection and precedence from the real shell function;
`test_temp.sh` sources the real WAV allocation/cleanup functions and checks
randomization plus 0700/0600 modes on BSD or GNU tools; `test_lock.sh` sources
the real audio_lock/audio_unlock and proves concurrent workers serialize and a
killed holder's lock auto-releases (self-skips where lockf is absent).
`.github/workflows/ci.yml` runs bash -n, py_compile, the unittests, and the lock
test on both Linux and macOS, plus ShellCheck once on Linux (its analysis is
platform-independent; intentional indirect-use findings are suppressed inline
with rationale). macOS is the real target (bash 3.2 + BSD utils); actions are
pinned to commit SHAs, checkout credentials are not persisted, superseded runs
are cancelled, and jobs have a 20-minute ceiling. The macOS job builds and
launches both Swift helpers, validating their documented AVAILABLE/UNAVAILABLE
and BUSY/IDLE diagnostic contracts. Only live Foundation Models inference
remains locally verified because it requires macOS 26 with Apple Intelligence
enabled.

Hook changes only affect new Claude sessions; running sessions keep the hook
snapshot from their start.

## Debugging

Silent hooks are otherwise opaque, so the hook has a `dbg` trace: set
`CLAUDE_ANNOUNCE_DEBUG=1`, or `touch ~/.local/share/claude-ai-notifs/debug`
(the flag file needs no env var, which matters because the hook is spawned by
Claude Code, not launched by hand), and it appends its decisions to
`~/.local/share/claude-ai-notifs/debug.log`: host terminal, gate/focus outcome,
task length, which summarizer produced the sentence (and its length), and the
final action (kokoro wav / say / ding / banner). This is how the "Ghostty
dinged" report was traced to a one-off model cold-start rather than a bug.
Remove the flag file to disable.
