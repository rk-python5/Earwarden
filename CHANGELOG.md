# Changelog

All notable changes to Earshot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow Semantic Versioning,
written in PEP 440 form (see D-006 in [decisions.md](decisions.md)).

## [Unreleased]

### Added

- `dev/false_approvals.py`, the recorded-audio check for false approvals, run by hand on the Mac
  (D-023). It sends Step 0's recordings through the daemon's own listening path.

### Fixed

- Noise and cut-off replies are no longer heard as approvals (P-20, D-027).
  - Silero VAD must hear speech in a reply before Parakeet does.
  - A reply that began before the listening window, for example while you talked over Earshot,
    is never parsed; Earshot asks again.
  - On Step 0's recordings, Parakeet alone approved 38 of 134 room-sound clips and 139 of 1,297
    cut-off non-approvals. Now none get through, and every real approval is still heard.
  - A live check with the AirPods still found one false approval: VAD dropped a short "no", then
    let a faint sound through that Parakeet heard as "Yeah.". P-20 stays open, and voice is for
    a scratch project only.

## [0.1.0] - 2026-11-08

Phase 1, the walking skeleton. A real Claude Code session was approved by voice through AirPods,
end to end, and the Phase 1 gate passed (D-026). Use voice only in a scratch project until P-20 is
fixed.

### Added

- The Phase 1 plan (`docs/phase-1-plan.md`): nine milestones in build order, which ones need
  rehaan's Mac, and the decisions each one needs.
- `earshot-hook`, Claude Code's command hook (Phase 1, milestone 1):
  - It uses only the standard library and always exits 0.
  - It prints nothing but a valid decision for a PermissionRequest; anything else hands off to
    Claude Code's own dialog.
  - It passes session and tool events on without waiting.
  - It's tested for every fail-safe path against a stand-in daemon, with payloads captured from
    Claude Code 2.1.318.
- The five message contracts (`earshot.contracts`), with Pydantic as the first runtime
  dependency, and the wire format and file locations shared by the hook and the daemon.
- `earshotd`, the background service's core (Phase 1, milestone 2):
  - It listens on a Unix socket that only you can reach, and checks each message's contract
    and the shared token. Anything that fails gets no reply, so the hook hands off.
  - It keeps track of sessions and of requests waiting for an answer.
  - A request ends when the decider answers (for now always a hand-off to the screen), when
    you approve it on screen and the tool runs, when you press No or Esc, when its session
    ends, when the daemon stops, or at the wait limit (D-020).
  - It replaces a socket left behind by a crash, and refuses to start twice.
- `earshot init`, `earshot uninstall` and observe mode (Phase 1, milestone 3):
  - `init` adds Earshot's hooks to a Claude Code settings file next to your own, keeping a
    byte-for-byte backup; `uninstall` removes only Earshot's and restores the backup when
    nothing else changed.
  - `earshotd --observe` logs each permission prompt (time, session, mode, tool, and whether the
    safety stub would let voice approve it) and never answers. `earshot observe` summarises the
    log.
  - The safety stub (D-019) decides what voice may approve until Phase 2's policy engine.
- The template narrator (Phase 1, milestone 4): one sentence per request for the six action
  families, test runs and a fallback, with the spec's spoken forms ("routes dot p y, in the api
  folder"). Secrets are redacted before anything is spoken or logged, and a request holding one
  never goes to voice. Sentences over 25 words aren't spoken, and words the voice can't
  pronounce are spelled out (D-024).
- The audit log (Phase 1, milestone 7): every decision the daemon resolves becomes one JSON line
  in a hash chain keyed with HMAC-SHA256 (the key in the Keychain on a real install), with
  secrets redacted. `earshot audit verify` catches edited, deleted and reordered lines, and
  `earshot audit tail` shows the latest decisions.
- The voice path (Phase 1, milestones 5 and 6), behind `earshotd --voice`:
  - Only when you're away from the keyboard (or with `--pin-voice`) and the AirPods are the
    output, Earshot plays the session's chime and says the request.
  - For what the safety stub allows, it asks "Approve?" and listens. "Yes" approves, "no" denies,
    "no, use poetry instead" denies with that message for the agent, "wait" hands off. One
    unclear answer is asked again; silence is re-asked after a minute, up to three times.
  - Everything else is only announced, with "it's on your screen".
  - Kokoro speaks; Parakeet transcribes, with Whisper as the second listen when Parakeet is
    unclear (D-017). Talking over Earshot stops it.
  - The voice libraries are a separate, Mac-only install group: `uv sync --group voice`.
- `earshot service install` and `uninstall` (a LaunchAgent that starts `earshotd` at login and
  restarts it), `earshot doctor` (hooks, token, daemon, voice libraries, headset, LaunchAgent,
  audit log), and `earshot test` (one made-up request through the running daemon). Phase 1,
  milestones 8 and 9.
- An end-to-end test that replays rehaan's captured Claude Code session through the real hook and
  daemon.
- `docs/next-steps.md`, the hand-over from cloud sessions to Claude Code on the Mac: how to run
  the Phase 1 gate, the likely first fixes, and how to start Phase 2.
- Decided before Phase 1:
  - a safety stub that keeps risky requests off voice until Phase 2's policy engine (D-019)
  - how Earshot behaves while a hook waits (D-020)
  - auto mode as a first filter, with a week of observe mode (D-021)
  - Earshot's own Kokoro text front-end, clear of GPL code (D-022)
- Decided to finish Phase 1 now (D-023 to D-025): the observe week is optional, the mic helper
  and Silero VAD move to Phase 2, summaries must be speakable, only exact answers count, and the
  audit chain is keyed.
- Recorded the Phase 1 gate as passed (D-026), and P-20: non-speech and cut-off replies can be
  heard as approvals. It's the first fix in Phase 2; until then, voice is for a scratch project
  only.
- `earshotd --voice` logs which mic it opened and at what rate, each listen's noise floor,
  threshold and loudest level, and which recognizer answered and how fast. It logs no audio
  and no transcripts.

### Changed

- Secret redaction no longer mistakes a long file path for a key.
- CI runs as one macOS job instead of two: GitHub's Mac runners kept leaving one of the two
  waiting until its timeout. The Swift build still runs even when a Python check fails.

### Fixed

- The voice no longer asks Hugging Face for model updates at every start. Once all three models
  are cached, they load with the Hub offline, so nothing leaves the Mac, and loading takes 5 s
  instead of 37 s.
- A voice cancelled because you answered on screen now stops before the next request speaks.
  Before, its final stop could cut off the next request's speech. The device list is no longer
  refreshed while Earshot is speaking.
- The LaunchAgent passes on `HF_HOME` and `HF_HUB_CACHE` from the shell that installs it.
  Started by launchd, the daemon would otherwise have downloaded the models again into
  `~/.cache` instead of using the ones in `.tools/` (D-013).

## [0.0.2] - 2026-11-04

Step 0's results. All four week-1 tests ran on rehaan's Mac and passed, and the Step 0 gate passed
(D-014).

### Added

- `dev/activate`, sourced once per terminal on the Mac. It keeps uv, the Python it downloads, every
  library, the spike scripts' environments and model downloads inside the repo, under the
  git-ignored `.tools/` (D-013).
- First Step 0 results, from the hook probe on rehaan's Mac (`spikes/RESULTS.md`, section 1). Allow
  and deny from a hook work, and Q-1 is answered: Claude Code shows its own dialog while the hook is
  still running, and whichever answers first wins. P-12 is revised to match, and P-15 (auto mode)
  is new.
- `spikes/speech/combine.py`: works out a two-stage recogniser from two finished runs, a fast one
  first and a second listen only when it's unclear, judged with Earshot's rules. The challenge-word
  rule now lives in the tested `speech_data.py`.
- Head-motion results (`spikes/RESULTS.md`, section 5): motion works from a signed app at 50 Hz,
  with nods on x and shakes on z, but the plan's v1 detector gives about 48 false nods an hour
  (P-18).
- The Step 0 gate passed on 4 Nov 2026 (D-014). Decided at the gate:
  - the answer window can't hear Earshot's own prompt (D-015)
  - a signed Swift helper owns mic capture and the other macOS plumbing (D-016)
  - two-stage recognition, Parakeet then Whisper (D-017)
  - nods don't approve on their own (D-018)
  - the per-word confidence score (P-05) is rejected
- Voiceprint results (`spikes/RESULTS.md`, section 6): rehaan's voice and a friend's separate by
  +0.112 with the silence trimmed, and ECAPA in ONNX matches PyTorch at every length. The
  onnxruntime process peaks at 206 MB, about twice the estimate. All four week-1 tests now have
  results.
- `spikes/motion/run.sh` builds the head-motion spike as a small signed app and opens it as its own
  app. Started from Terminal, macOS stopped it with `abort`, because the program counted as
  Terminal's and Terminal declares no use of motion data. CI now builds and checks the app.
- Motion calibration waits for motion data before its countdown, and reports each axis's typical
  speed in rad/s.

### Changed

- Setup instructions use `source dev/activate` instead of installing uv system-wide.
- The hook probe report credits each tool run to its own request, even when a refused command is
  asked for again. It also says who decided: the hook, or you on screen.
- The speech evaluation lists every misheard reply and can cut the silence around replies first
  (`--trim`). It also adds two what-ifs for challenge phrases (lenient "approve", and the challenge
  word alone), and can compare other recognisers such as Parakeet v3, Whisper and Moonshine
  (`--model`).
- The voiceprint report lists every phrase's score, and adds a gap over only the phrases both
  speakers said outside the profile. It can cut the silence around each phrase first (`--trim`).

### Fixed

- The voiceprint spike's ONNX check also cuts each recording to shorter lengths. Every recording
  is 3 seconds long, so the check had covered only one length.
- The voiceprint report's model size counts the weights. The exporter writes them to a separate
  file, so the report had shown 0.6 MB for an 83 MB model.

## [0.0.1] - 2026-11-03

The Step 0 kit: project conventions, the package scaffold, CI, and the feasibility spikes ready to
run on the Mac.

### Added

- Technical design and build plan (revision of 3 Nov 2026) in `docs/design/`.
- `CLAUDE.md`, `decisions.md` and this changelog.
- Python package scaffold: distribution `earshot-agents`, import name `earshot`, managed with uv on
  Python 3.11, checked with ruff, strict mypy and pytest.
- Tests that keep the version, the changelog and the installed metadata in step, and that keep
  `import earshot` free of other imports.
- CI on GitHub Actions (macOS 15, Apple Silicon): lint, format, strict types and tests on every push
  to `main`.
- Step 0 hook probe (`spikes/hook_probe`): a stdlib-only Claude Code hook. It logs every event,
  answers `PermissionRequest` with none, allow, deny or a timed hold, and comes with tools to
  install it in a scratch project, time it and report the round trip. It answers Q-1. Results go in
  `spikes/RESULTS.md`, the go/no-go note.
- Step 0 speech spike (`spikes/speech`):
  - Kokoro time to first audio.
  - A 50-reply recording kit, with decoy and negation replies, for quiet and noisy rooms.
  - Parakeet evaluation with a per-word confidence score and a false-approval count.
  - A pronunciation-coverage check that runs on any OS. Its first result: without espeak-ng, 47.6%
    of the top 1,000 PyPI names would be skipped in speech.
- Step 0 AirPods I/O spike (`spikes/audio_io`): mic switch delay (Q-2), playback leak and
  output-to-mic delay, and a self-approval check (P-06).
- Step 0 launchd microphone check (`spikes/launchd_mic`): runs a mic recording as a one-off launchd
  agent and from Terminal, to see whether macOS grants the mic and whether the grant survives an
  interpreter change (P-13).
- Step 0 head-motion spike (`spikes/motion`): a Swift command-line tool on `CMHeadphoneMotionManager`.
  It has three modes: `calibrate` finds the nod and shake axes, `count` counts false nods over an
  hour of normal work with the plan's v1 detector, and `log` streams JSON lines. CI builds it on
  macOS.
- Step 0 voiceprint spike (`spikes/voiceprint`): ECAPA scores for your phrases against a friend's,
  with the gap between them. It also exports ECAPA to ONNX, checks parity with PyTorch at every
  phrase length, and measures an onnxruntime-only process.
- The go/no-go note (`spikes/RESULTS.md`) maps the plan's four week-1 tests to the spike sections
  and lists what gets decided at the gate.

[Unreleased]: https://github.com/rk-python5/Earshot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rk-python5/Earshot/compare/v0.0.2...v0.1.0
[0.0.2]: https://github.com/rk-python5/Earshot/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/rk-python5/Earshot/releases/tag/v0.0.1
