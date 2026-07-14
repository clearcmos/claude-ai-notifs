# CLAUDE.md

Spoken announcements for Claude Code sessions in macOS Terminal.app. See
README.md for the user-facing overview; this file records what matters when
changing the code.

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
  session tty and asks Terminal.app directly via AppleScript, checking focus
  twice: before doing any work and again right before playback.
- Summarizer is Apple's on-device foundation model (FoundationModels
  framework, macOS 26+, Apple Intelligence must be enabled), replacing Ollama.
  Fallback chain: on-device model -> `claude -p --model haiku` (guarded
  against hook recursion via CLAUDE_ANNOUNCE_INNER) -> plain ding.
- The full instruction goes in the prompt with a "One-sentence announcement:"
  trailer, not in the session instructions. Tested: with the instruction in
  `LanguageModelSession(instructions:)` the small on-device model echoes the
  assistant reply verbatim instead of summarizing.
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
- Playback is serialized (2026-07-14): two sessions finishing at once used to
  talk over each other. audio_lock/audio_unlock in bin/claude-announce is a
  mkdir mutex on /tmp/claude-announce-audio-<uid>.lock (macOS has no flock, and
  a fixed per-user path outside $TMPDIR guarantees all the user's sessions
  share it), so concurrent announcements queue and play back-to-back. Both the
  main afplay/say path and the ding fallback take it; the focus/meeting state
  is re-checked after acquiring the lock (the wait may have been long); a
  crashed holder is reclaimed via its recorded PID with a ~120s backstop;
  playback is with_timeout-bounded so the lock is held only seconds; and an
  EXIT trap releases it on every exit path, including the meeting-banner exit.

## Deployment

`setup.sh` is idempotent: venv + model downloads + swiftc build into
`~/.local/share/claude-ai-notifs`, then wires `hooks.Stop` and
`hooks.Notification` in `~/.claude/settings.json` by absolute repo path
(backing up the file first). `setup.sh --test` speaks one announcement from
the newest transcript with focus checks bypassed (CLAUDE_ANNOUNCE_FORCE=1).

Hook changes only affect new Claude sessions; running sessions keep the hook
snapshot from their start.
