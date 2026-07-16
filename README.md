# claude-ai-notifs

Spoken AI notifications for Claude Code sessions in supported macOS terminals.
When a Claude session finishes a turn or needs your input or permission while
you are looking at another tab, window, or app, a synthesized voice tells you
what happened ("Claude fixed the failing auth tests, all 47 now pass") instead
of a plain ding.

At install you pick which of your installed terminals it runs in (see the
support matrix below); it stays silent in the rest.

Before you install, two things that shape the experience:

- **Apple Silicon Mac.** Apple Silicon is required; macOS 26 is not. The fast
  on-device summarizer needs macOS 26 with Apple Intelligence enabled. On older
  macOS releases, or when Apple Intelligence is unavailable, summaries fall
  back to `claude -p --model haiku`, which uses your Claude plan (or API
  billing) and adds a few seconds per announcement.
- **Tab-level "are you looking at it?" detection varies by terminal.** Most
  supported terminals can tell whether the finishing session is the tab you are
  actually viewing, so the voice stays quiet when you are watching and speaks
  when you are elsewhere; some cannot expose that information. See the matrix.

This started as a macOS port of a personal Linux setup built around a patched
foot terminal (the terminal owned the tab-focus logic there); on macOS each
focus-capable terminal is queried directly (AppleScript, or its CLI) instead.

## How it works

1. Claude Code `Stop` and `Notification` hooks run `bin/claude-announce`.
2. It reads the terminal hosting the session from the environment; if that
   terminal is not one you enabled at install, it stays silent. Otherwise it
   decides, where the terminal supports it, whether you are looking at this
   session's tab: it climbs the process tree to the session's tty and asks the
   frontmost terminal - via AppleScript (Terminal.app, iTerm2, supported
   Ghostty builds) or the terminal's CLI (WezTerm, kitty) - whether that tty is
   the visible tab/pane. If you are looking at it, nothing plays. If exact
   session focus cannot be determined, it speaks rather than risk dropping an
   announcement.
3. `bin/claude-announce-extract.py` pulls the last user prompt and Claude's
   final reply (or the pending question/permission ask) out of the session
   transcript.
4. Apple's on-device foundation model (Apple Intelligence, macOS 26) compresses
   that into one spoken sentence via the compiled
   `claude-announce-summarize` binary. If the model is unavailable, it falls
   back to `claude -p --model haiku`.
5. Kokoro TTS (af_heart voice, same as the Linux setup) synthesizes the
   sentence and `afplay` speaks it. Focus is re-checked before playback, and
   playback is serialized across sessions - if two sessions finish at once the
   announcements queue and play back-to-back instead of talking over each
   other.
6. On macOS 14.4+, the voice stays quiet while the microphone is in use: when
   any process is capturing it (Zoom, Google Meet, Teams, Webex, Slack huddles,
   FaceTime - muted-but-joined included), the summary arrives as a silent macOS
   banner notification instead. Dictation and audio recording suppress the
   voice the same way. Mic state is re-checked right before playback in case a
   call starts mid-generation. If the CoreAudio check is unavailable or fails,
   the tool fails open toward speaking.

Every stage degrades: no summary means the plain Glass ding (a generic banner
in a meeting), no Kokoro means the native `say` voice. The hook always exits 0,
so it can never fail a session, and setup wires it with `async: true`, so the
several seconds of summarizing, synthesizing, and playback run in the background
and never delay the next turn.

## Supported terminals

`setup.sh` offers only the terminals actually installed; pick one or more, and
re-run any time to add more.

| Terminal | Focus detection | Mechanism |
| --- | --- | --- |
| Terminal.app | tab-level | AppleScript |
| iTerm2 | tab-level | AppleScript |
| Ghostty | tab-level when its AppleScript API exposes `tty`; v1.3.1 and older always speak | AppleScript (`tty` property) |
| WezTerm | pane-level | `wezterm cli` |
| kitty | tab-level; needs remote control (setup enables it, restart kitty) | `kitty @ ls` |
| Alacritty | none - always speaks, even while you are viewing its window | unavailable (no focused-window query) |

"tab-level" means the voice stays silent while you are looking at the session
and speaks when you are on another tab, window, or app. Where per-tab detection
is unavailable (Alacritty, or Ghostty on v1.3.1 and older), it speaks whenever
the `Stop` or `Notification` hook fires, even if you are watching the session.
Ghostty added the required `tty` property after v1.3.1
([PR #11922](https://github.com/ghostty-org/ghostty/pull/11922)). Until a stable
release includes it, use a tip build for tab-level detection. Focus queries
only run when that terminal is frontmost and (Terminal.app/iTerm2/Ghostty) may
trigger a one-time macOS Automation prompt to allow.

## Requirements

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
./setup.sh          # venv + ~340 MB models + summarizer, then pick terminals, wire hooks
./setup.sh --terminals "ghostty,iterm2"   # non-interactive terminal choice (keys)
./setup.sh --test   # deliver a test announcement from the newest transcript
```

Setup detects your installed terminals and asks which to announce in
(multi-select). The terminal keys are: `terminal`, `iterm2`, `ghostty`,
`wezterm`, `kitty`, `alacritty`. The test command requires at least one existing
Claude transcript; it speaks normally or sends a silent banner if the
microphone is in use.

Notes if you are not the author:

- Existing hooks in `~/.claude/settings.json` are preserved; setup only
  appends its own Stop/Notification entries (and re-runs replace them).
- The Kokoro models (~340 MB) are downloaded from the `thewh1teagle/kokoro-onnx`
  GitHub release and verified by SHA-256 against the known release hashes before
  use (a mismatch aborts and re-downloads); setup needs network for that and for
  the pip install. Python dependencies install from a hash-locked
  `requirements.lock` (`--require-hashes`, full transitive tree), generated from
  `requirements.txt`.
- Re-run any time to enable additional terminals (newly installed or previously
  skipped); the picker pre-checks your current selection. Selecting kitty adds
  `allow_remote_control` to your `kitty.conf` (restart kitty to apply).
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
bin/claude-announce              hook entry point (stop | notification)
bin/claude-announce-extract.py   transcript -> announcement material
bin/claude-announce-hooks.py     settings.json wiring (wire | unwire)
bin/claude-announce-tts.py       Kokoro synthesis (runs in the venv)
src/claude-announce-summarize.swift  Apple Foundation Models CLI
src/claude-announce-miccheck.swift   CoreAudio microphone-use detector
setup.sh                         installer / smoke test
requirements.txt                 direct Kokoro deps (source for the lock)
requirements.lock                hash-locked full dependency tree (installed)
tests/                           unit tests (transcript extractor + hook wiring)
```

Run the automated tests with:

```sh
python3 -m unittest discover -s tests   # stdlib only; no install needed
bash tests/test_lock.sh                 # audio-lock concurrency
```

They cover the transcript extractor (turn scoping, anti-hallucination,
slash-command, and notification logic), settings.json hook wiring (structural
matching, idempotence, migration, uninstall, and atomic writes), and audio-lock
serialization and kill-release behavior. CI runs bash syntax checks, Python
compilation, and the unit tests on Linux and macOS for pull requests and pushes
to `main`. The lock test exercises `lockf` on macOS and self-skips where it is
unavailable; ShellCheck runs once on Linux, and the hash-locked dependency
install is tested once on macOS. CI does not build the Swift helpers, which are
verified locally; the Foundation Models summarizer specifically requires macOS
26 with Apple Intelligence.

Runtime artifacts live in `~/.local/share/claude-ai-notifs` (venv, models,
compiled summarizer and microphone checker, and the `enabled-terminals` list);
the hooks reference the scripts in this repo by absolute path.

## Troubleshooting

If a session dings instead of speaking, or stays silent when you expected a
voice, turn on the decision trace and reproduce it:

```
touch ~/.local/share/claude-ai-notifs/debug     # enable
# ...run a Claude session in the terminal in question...
cat  ~/.local/share/claude-ai-notifs/debug.log   # read what happened
rm   ~/.local/share/claude-ai-notifs/debug       # disable
```

The log shows the host terminal, whether it was gated or focused, the task and
summary lengths, which summarizer was used, and the final action - enough to
see which stage came up empty. (A one-off ding is usually the on-device model's
first-call cold start; it warms up after that.)

## Uninstall

```
./setup.sh --uninstall
```

Removes the `claude-announce` entries from `hooks.Stop` and
`hooks.Notification` in `~/.claude/settings.json` (other hooks and settings
untouched, with a backup written first) and deletes
`~/.local/share/claude-ai-notifs` (including the `enabled-terminals` list).
Delete the repo directory afterwards. Already-running Claude sessions keep their
hook snapshot until restarted. If you enabled kitty, the `allow_remote_control`
block added to your `kitty.conf` is left in place; remove it manually if you
want.

If `settings.json` is not valid JSON (or `python3` is unavailable), uninstall
cannot edit it safely. Rather than report a clean uninstall it did not perform,
it leaves both the runtime directory and this repo in place (the live hooks
still point into the repo), warns you to delete the `claude-announce` entries
under `hooks.Stop`/`hooks.Notification` by hand, and exits nonzero.
