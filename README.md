# claude-ai-notifs

Spoken AI notifications for Claude Code sessions in macOS Terminal.app. When a
Claude session finishes a turn or waits on a permission prompt while you are
looking at another tab, window, or app, a synthesized voice tells you what
happened ("Claude fixed the failing auth tests, all 47 now pass") instead of a
plain ding.

This started as a macOS port of a personal Linux setup built around a patched
foot terminal (the terminal owned the tab-focus logic there). Terminal.app
exposes tab focus over AppleScript, so no terminal changes are needed on
macOS.

## How it works

1. Claude Code `Stop` and `Notification` hooks run `bin/claude-announce`.
2. The script climbs its process tree to the session's tty and asks
   Terminal.app whether that tab is the selected tab of the front window while
   Terminal is frontmost. If you are looking at it, nothing plays.
3. `bin/claude-announce-extract.py` pulls the last user prompt and Claude's
   final reply (or the pending question/permission ask) out of the session
   transcript.
4. Apple's on-device foundation model (Apple Intelligence, macOS 26) compresses
   that into one spoken sentence via the compiled
   `claude-announce-summarize` binary. If the model is unavailable, it falls
   back to `claude -p --model haiku`.
5. Kokoro TTS (af_heart voice, same as the Linux setup) synthesizes the
   sentence and `afplay` speaks it. Focus is re-checked before playback.

Every stage degrades: no summary means the plain Glass ding, no Kokoro means
the native `say` voice. The hook always exits 0 and can never block a session.

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
./setup.sh          # venv + ~340 MB Kokoro models + summarizer + hook wiring
./setup.sh --test   # speak one announcement from the newest transcript
```

Notes if you are not the author:

- Focus detection only knows Terminal.app. In iTerm2, Ghostty, or an IDE
  terminal the focus check fails open, so announcements play even while you
  are looking at the session. Everything else works.
- Existing hooks in `~/.claude/settings.json` are preserved; setup only
  appends its own Stop/Notification entries (and re-runs replace them).
- Without Apple Intelligence enabled, summaries fall back to
  `claude -p --model haiku`, which uses your Claude plan (or API billing) and
  adds a few seconds per announcement.

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
bin/claude-announce-tts.py       Kokoro synthesis (runs in the venv)
src/claude-announce-summarize.swift  Apple Foundation Models CLI
setup.sh                         installer / smoke test
```

Runtime artifacts live in `~/.local/share/claude-ai-notifs` (venv, models,
compiled summarizer); the hooks reference the scripts in this repo by absolute
path.

## Uninstall

```
./setup.sh --uninstall
```

Removes the `claude-announce` entries from `hooks.Stop` and
`hooks.Notification` in `~/.claude/settings.json` (other hooks and settings
untouched, with a backup written first) and deletes
`~/.local/share/claude-ai-notifs`. Delete the repo directory afterwards.
Already-running Claude sessions keep their hook snapshot until restarted.
