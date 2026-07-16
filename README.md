# claude-ai-notifs

Spoken AI notifications for Claude Code sessions in supported macOS terminals.
When a Claude session finishes a turn or waits on a permission prompt while you
are looking at another tab, window, or app, a synthesized voice tells you what
happened ("Claude fixed the failing auth tests, all 47 now pass") instead of a
plain ding.

At install you pick which of your installed terminals it runs in (see the
support matrix below); it stays silent in the rest.

Before you install, two things that shape the experience:

- **Apple Silicon Mac, macOS 26+.** Apple Silicon is required. The fast
  on-device summarizer additionally needs macOS 26 with Apple Intelligence
  enabled; without it, summaries fall back to `claude -p --model haiku`, which
  works but uses your Claude plan (or API billing) and adds a few seconds per
  announcement.
- **Tab-level "are you looking at it?" detection varies by terminal.** Most
  supported terminals can tell whether the finishing session is the tab you are
  actually viewing, so the voice stays quiet when you are watching and speaks
  when you are elsewhere; a couple can only do this partially. See the matrix.

This started as a macOS port of a personal Linux setup built around a patched
foot terminal (the terminal owned the tab-focus logic there); on macOS each
terminal is queried directly (AppleScript, or its CLI) instead.

## How it works

1. Claude Code `Stop` and `Notification` hooks run `bin/claude-announce`.
2. It reads the terminal hosting the session from the environment; if that
   terminal is not one you enabled at install, it stays silent. Otherwise it
   decides whether you are looking at this session's tab: it climbs the process
   tree to the session's tty and asks the frontmost terminal - via AppleScript
   (Terminal.app, iTerm2, Ghostty) or the terminal's CLI (WezTerm, kitty) -
   whether that tty is the visible tab/pane. If you are looking at it, nothing
   plays.
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
6. In a meeting the voice stays quiet: when any process is capturing the
   microphone (Zoom, Google Meet, Teams, Webex, Slack huddles, FaceTime -
   detected via CoreAudio, muted-but-joined included), the summary arrives as
   a silent macOS banner notification instead. Any other mic use (dictation,
   audio recording) suppresses the voice the same way. Mic state is
   re-checked right before playback in case a call starts mid-generation.

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
| Ghostty | tab-level on builds newer than v1.3.1; older builds announce every turn | AppleScript (`tty` property) |
| WezTerm | pane-level | `wezterm cli` |
| kitty | tab-level; needs remote control (setup enables it, restart kitty) | `kitty @ ls` |
| Alacritty | none - announces every turn | app frontmost only |

"tab-level" means the voice stays silent while you are looking at the session
and speaks when you are on another tab, window, or app. Where per-tab detection
is unavailable (Alacritty, or Ghostty on v1.3.1 and older), the tool errs
toward speaking - it never silently drops an announcement. Focus queries only
run when that terminal is frontmost and (Terminal.app/iTerm2/Ghostty) may
trigger a one-time macOS Automation prompt to allow.

## Requirements

Ships with macOS: `osascript`, `afplay`, `say`, `curl`. Needed on a new
machine:

- Apple Silicon Mac on macOS 26+
- Xcode Command Line Tools (`xcode-select --install`) for `swiftc`
- Python 3.10+ (`brew install python@3.12`) or `uv`, for the Kokoro venv
- Claude Code CLI (already present if you run Claude sessions)
- Apple Intelligence enabled in System Settings > Apple Intelligence & Siri
  (optional; without it the summarizer falls back to `claude -p`)

## Setup

```
./setup.sh          # venv + ~340 MB models + summarizer, then pick terminals, wire hooks
./setup.sh --terminals "ghostty,iterm2"   # non-interactive terminal choice (keys)
./setup.sh --test   # speak one announcement from the newest transcript
```

Setup detects your installed terminals and asks which to announce in
(multi-select). The terminal keys are: `terminal`, `iterm2`, `ghostty`,
`wezterm`, `kitty`, `alacritty`.

Notes if you are not the author:

- Existing hooks in `~/.claude/settings.json` are preserved; setup only
  appends its own Stop/Notification entries (and re-runs replace them).
- The Kokoro models (~340 MB) are downloaded from the `thewh1teagle/kokoro-onnx`
  GitHub release and verified by SHA-256 against the known release hashes before
  use (a mismatch aborts and re-downloads); setup needs network for that and for
  the pip install. Python dependencies are version-pinned in `requirements.txt`.
- Re-run any time to enable additional terminals (newly installed or previously
  skipped); the picker pre-checks your current selection. Selecting kitty adds
  `allow_remote_control` to your `kitty.conf` (restart kitty to apply).
- See the support matrix above for per-terminal focus behavior, and the note at
  the top about the macOS 26 / Apple Intelligence summarizer fallback.

Re-runnable. Hook wiring backs up `~/.claude/settings.json` first and, if an
older `notify-unfocused.sh` Notification hook is present, replaces it (this
supersedes that approach). Hooks take effect in new Claude sessions, not
already-running ones.

The first announcement from a given app context may trigger a macOS Automation
permission prompt (controlling Terminal via AppleScript); allow it once.

## Layout

```
bin/claude-announce              hook entry point (stop | notification)
bin/claude-announce-extract.py   transcript -> announcement material
bin/claude-announce-hooks.py     settings.json wiring (wire | unwire)
bin/claude-announce-tts.py       Kokoro synthesis (runs in the venv)
src/claude-announce-summarize.swift  Apple Foundation Models CLI
setup.sh                         installer / smoke test
requirements.txt                 pinned Kokoro venv dependencies
tests/                           unit tests (transcript extractor + hook wiring)
```

Run the tests with `python3 -m unittest discover -s tests` (stdlib only, no
install needed). They cover the transcript extractor (turn scoping,
anti-hallucination, slash-command, and notification logic) and the settings.json
hook wiring (structural matching, idempotence, migration, uninstall, atomic
write); the same checks run in CI on every push (`.github/workflows/ci.yml`), on
both Linux and macOS. The Swift components need macOS 26 with Apple
Intelligence, so they are verified locally rather than in CI.

Runtime artifacts live in `~/.local/share/claude-ai-notifs` (venv, models,
compiled summarizer, and the `enabled-terminals` list); the hooks reference the
scripts in this repo by absolute path.

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
cannot edit it safely: it still removes the runtime directory but prints a
warning telling you to delete the `claude-announce` hook entries by hand, rather
than reporting a clean uninstall it did not perform.
