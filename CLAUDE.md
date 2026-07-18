# CLAUDE.md

Spoken announcements for Claude Code sessions in supported macOS terminals
(Terminal.app, iTerm2, Ghostty, WezTerm, kitty, Alacritty) and foot on
Linux/Wayland. See README.md for the user-facing overview; this file records
what matters when changing the code.

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
- Public Linux foot delivery (2026-07-16): the hook no longer depends on the
  clearcmos fork's `${pty}` bell template. It synthesizes into a private random
  token directory and writes OSC 777 `notify;claude-ai-notifs;<token>` to the
  session pty. Upstream foot and the fork both apply
  `[desktop-notifications] inhibit-when-focused=yes` to the terminal object
  receiving that OSC; the fork transfers `kbd_focus` between terminal objects
  when tabs change, so this is tab-accurate there. The installed
  claude-announce-foot dispatcher validates and atomically claims the token,
  serializes playback with Linux flock(1), checks microphone capture at actual
  playback time, and deletes the item. It reconstructs foot's normal
  notify-send call for every unrelated notification, including action
  arguments and activation stdout. `CLAUDE_ANNOUNCE_FORCE=1` directly
  dispatches only for setup's audible test.
- Linux summarization uses Ollama's HTTP API with the same grounded
  status/evidence/topic prompt and claude-announce-render.py validator as the
  macOS Foundation Models and Haiku paths. The assessment request supplies a
  JSON schema and a five-minute keep_alive. Runtime endpoint precedence is an
  explicit env host, then setup's persisted endpoint, then loopback; setup never
  scans the LAN. API reachability,
  not a binary or systemd unit, is authoritative, so manual, containerized,
  user-service, system-service, and explicit remote servers work. Model pulls
  happen only during setup after confirmation, never in a hook.
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
- Event-native pending input (2026-07-17): Claude Code explicitly documents
  that `transcript_path` writes are asynchronous and can lag the live dialog.
  `AskUserQuestion` is therefore announced from an async
  `PreToolUse` hook's exact `tool_input.questions`; normal tool approvals use
  async `PermissionRequest` and its exact `tool_name`/`tool_input`. A
  PermissionRequest whose tool_name is AskUserQuestion is suppressed
  (2026-07-17, real complaint): both hooks fire for that single pause, so
  every question spoke two sentences. The pending helper exits 3 with no
  output for that payload and the hook exits silently; exit 3 is distinct
  from empty output, so genuine extraction failures still fall back to a
  ding rather than silence.
  `Notification` no longer matches `permission_prompt` (which would duplicate
  those event-native hooks); it remains for `agent_needs_input` and
  `elicitation_dialog`, using the documented `message` field. The separate
  claude-announce-pending.py owns these payload shapes, while the shared
  transcript extractor remains a compatibility fallback only. All four hook
  forms are exec-form + async and are structurally wired/unwired together.
- Compile the Swift CLI with `-parse-as-library` (single-file swiftc builds
  treat the file as main.swift, which rejects `@main`).
- TTS is kokoro-onnx with the af_heart voice, matching Linux. macOS playback
  is a fallback chain in play_summary (bin/claude-announce): kokoro wav via
  afplay, then native `say` (covers a missing venv/models AND an afplay
  failure - a timed-out TTS leaves a truncated wav that still passes `-s`),
  then the ding asset when `say` itself fails (missing voice data). Silence
  is the one unacceptable outcome; tests/test_playback.sh sources the real
  function with stubbed players and pins the chain order on both CI OSes.
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
  is not mislabeled as an explanation. `produced` is request-gated
  (2026-07-17, after real misses): reply evidence cannot distinguish supplied
  content from an explanation of existing code, and llama3.2:3b labeled a
  feature explanation `produced`, announcing "created the requested codebase".
  render.py now keeps `produced` only when the latest request itself asks for
  content, enforced as POSITIVE request grammar (content_request in
  render.py, hardened across four external-review rounds 2026-07-17): a
  base-form content verb (write/draft/summarize/...) at a true line start
  (optional bullet marker with trailing whitespace, optional opening quote)
  or governed by a directive matched anywhere ("can you write", "I need you
  to draft"), or a content noun governed by a fetch ("give me a summary",
  "we need a poem"). Vocabulary matching plus question detection was
  bypassable from both sides ("Can you explain how this generates a
  summary?" carried a directive marker that globally overrode question
  detection). Third-person verb forms ("generates", "writes") are
  deliberately absent: they describe existing behavior, never a directive.
  Sentence punctuation is deliberately not an imperative boundary
  (colon-introduced quotations like 'the docs say: "generate a summary"'
  would read as imperatives), so "Thanks. Write a summary." falls to neutral
  wording: an accepted false-negative cost. content_request preserves line
  breaks because flattening them erases the boundaries that make bullets
  trustworthy. ACCEPTED SEMANTIC BOUNDARY, not a mathematical guarantee: a
  standalone quoted phrase as the entire request ('"write a poem"') is
  irreducibly ambiguous between request and mention and is treated as a
  request. Unrecognized phrasings fail toward neutral wording, never toward
  a creation claim. The template verb is the softer
  "produced", and the
  assessment prompt carries a balanced `answered` example because few-shot
  label imbalance biases small classifiers toward exampled statuses (the
  model still often says `produced`; the gate, not the prompt, is the
  guarantee). `waiting` covers progress dependent on
  a future event/person/action, and `recapped` covers state/open-item summaries;
  their topics prefer concrete names, systems, projects, artifacts, or
  identifiers from the reply when the latest request is vague. Generic model
  topics (`request`, `task`, `issue`, `work`, `response`, `reply`) use truthful
  status-specific fallbacks instead. Haiku fallback
  produces the same JSON and passes through the same validator. With no recorded
  reply the status is forcibly neutral, and total model failure becomes the
  always-true "Finished responding" rather than an invented outcome.
  Modern hook replies are read directly from last_assistant_message and bounded
  with a head+tail slice so long replies retain their concluding qualifications;
  the shared extractor remains the compatibility fallback.
- Actor-free voice (2026-07-17, user preference): spoken sentences never name
  Claude - the voice has exactly one possible speaker, so the name was pure
  filler in first position. render.py templates are verb-first status readouts
  ("Made changes to X.", "Waiting on X."), the deterministic Stop fallback is
  "Finished responding.", the foot dispatcher's empty-summary fallback is
  "Attention needed", the Linux ding path's banner text is "Turn finished" /
  "Waiting for your input" matching macOS, and the pending task framings plus summarizer
  instruction avoid the name. Because the pending sentence is model-written,
  strip_actor in bin/claude-announce deterministically removes a leading
  actor phrase ("Claude is/has...", "The assistant needs...") at the point
  where all summarizer paths converge; auxiliaries (is/has/was/will) are
  dropped with the actor while semantic verbs (needs/wants) are kept so the
  fragment stays verb-first. Content mentions (a topic like "Claude Code
  hooks") are deliberately untouched, and visual banner titles keep the
  "Claude Code" attribution because a silent banner does need a source. The
  Linux runtime test feeds a fake summary that still names Claude and asserts
  the played text is stripped.
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

On macOS, `setup.sh` is idempotent: venv + model downloads + swiftc build into
`~/.local/share/claude-ai-notifs`, then an atomic self-contained runtime install,
then the terminal picker (writes
`enabled-terminals`, configures kitty if chosen), then wires Stop plus the
event-native pending-input hooks in `~/.claude/settings.json`. `setup.sh --test` delivers
one announcement from the newest transcript with both the focus check and the
terminal gate bypassed (CLAUDE_ANNOUNCE_FORCE=1 skips both); an active mic turns
that test into the same silent banner used at runtime.

On Linux, setup.sh immediately dispatches to setup-linux.sh. It completes a
read-only distro/capability preflight before asking for changes, supports
pacman/apt/dnf/zypper, displays the exact missing packages, and lets sudo own
the password prompt via `sudo -v`; the script never reads a password. Ollama is
probed after dependencies: a reachable API is reused, an existing stopped
system/user unit can be started, an unserviced binary can receive a narrowly
scoped user unit, and otherwise the separately confirmed official installer is
downloaded to a private file before execution. Python 3.12 is used when it has
venv/ensurepip support; otherwise setup can install uv privately under BASE
without modifying shell profiles. setup provisions llama3.2:3b by default,
creates the same locked Kokoro venv/assets, installs the same atomic runtime,
configures foot, and wires the hooks.

Linux foot configuration lives in a marked block written atomically by
claude-announce-foot-config.py and validated with `foot --check-config` before
replacement. setup records `$BASE/foot-config-path` BEFORE writing the block
(2026-07-16 ordering was the reverse; found in external review): uninstall
discovers the block only through that record, and restore on an untouched or
missing config is a no-op success, so recording intent first means an
interruption between the two writes cannot strand a block uninstall cannot
find. An explicit notification command/action template or disabled focus
inhibition requires confirmation. The block overlays rather than deletes old
settings, so uninstall removes only the marked block. If restore fails,
uninstall keeps BASE because foot may still point at its dispatcher. A user
Ollama unit is removed only when setup created that exact named unit; existing
Ollama installations and services are never removed.

Legacy Linux migration: settings.json and foot.ini may both be symlinks into
the user's dotfiles repository. Atomic writers resolve the write target while
leaving the symlink itself intact; backups remain beside the user-facing
settings path. setup structurally replaces the old `~/arch/bin/claude-announce`
hooks but leaves the old files and `[bell]` command available for running
sessions. Canonical-hash legacy Kokoro assets are hard-linked into BASE when
possible (copy fallback), avoiding another download and duplicate storage.

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

Hook shape: all wired entries use Claude Code's exec form
(`command`+an `args` mode) with `async:true`. Exec form runs the executable
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
cross-platform step that builds a venv, installs the lock with --require-hashes, and
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
`test_pending.py` exercises authoritative AskUserQuestion, PermissionRequest,
and Notification payload extraction, including an unflushed transcript;
`test_grounding.py` exercises assessment parsing, verbatim grounding,
status-specific evidence gates, and investigation-versus-change regressions;
`test_hooks.py` exercises claude-announce-hooks.py (structural matching including
spaced exec paths, idempotence, legacy migration, uninstall, atomic write);
`test_install.py` exercises the atomic versioned runtime, repo independence,
failed-upgrade rollback, permissions, and installed standalone uninstall;
`test_focus.py` covers WezTerm/kitty focus parsing; `test_requirements.py` guards
direct-pin lock drift; `test_foot_config.py` covers marked atomic foot config,
conflicts, idempotence, and restore; `test_foot.py` covers tokenized OSC
enqueue/claim/playback and ordinary notification forwarding; `test_ollama.py`
covers endpoint normalization, API probing, model discovery/pull, structured
generation, and keepalive; `test_linux_runtime.py` runs the installed Linux hook
end to end against fake Ollama/Kokoro/tty services; `test_linux_setup.py` proves
the public entrypoint's Linux dry run is read-only; `test_setup_logging.py`
proves the public QA toggle is private, non-installing on an existing runtime,
log-retaining, and standalone; `test_tts.py` verifies the Kokoro adapter and
its private output mode with fake runtime modules. These are stdlib unittest, loading
hyphenated targets by path so extract.py stays byte-identical to the Linux copy. `test_terminal.sh`
tests host-terminal detection and precedence from the real shell function;
`test_temp.sh` sources the real WAV allocation/cleanup functions and checks
randomization plus 0700/0600 modes on BSD or GNU tools; `test_lock.sh` sources
the real audio_lock/audio_unlock and proves concurrent workers serialize and a
killed holder's lock auto-releases (self-skips where lockf is absent);
`test_playback.sh` sources the real play_summary and proves the
afplay -> say -> ding fallback order with stubbed players on any OS.
`.github/workflows/ci.yml` runs bash -n, py_compile, the unittests, and the lock
test on both Linux and macOS, plus ShellCheck once on Linux (its analysis is
platform-independent; intentional indirect-use findings are suppressed inline
with rationale). macOS (bash 3.2 + BSD utils) and Linux/foot are real targets; actions are
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
pending-input detail, which summarizer produced the sentence, and the actual
playback/notification result. This is how the "Ghostty
dinged" report was traced to a one-off model cold-start rather than a bug.
Remove the flag file to disable.

Public QA toggle: `setup.sh --log-on` and `setup.sh --log-off` are standalone
actions. For an existing install they only create/remove `$BASE/debug`, tighten
`debug` and `debug.log` to 0600, and append an enable/disable marker; disabling
retains the log. A fresh `--log-on` performs normal setup and enables logging
only after installation succeeds. The toggle is read at every hook/foot
dispatcher invocation, so no terminal or Claude restart is needed. The log can
contain exact transcript-derived summaries and remains opt-in.
