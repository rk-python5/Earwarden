# Changelog

All notable changes to Earshot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow Semantic Versioning,
written in PEP 440 form (see D-006 in [decisions.md](decisions.md)).

## [Unreleased]

### Added

- Session activity and briefings (Phase 4, milestone 1). Each session records whether it's
  working (since when, and how many tools it has run), finished or idle, from its events.
  `daemon/briefing.py` turns the registry into "Three sessions. api: running 12 minutes, 14
  tools run. docs: waiting for you. deploy: finished 5 minutes ago.", five sessions at most, with
  no file contents or messages read aloud.
- The floor manager (Phase 4, milestone 2), `daemon/floor.py`: one voice, in the spec's order.
  - Approvals take the floor first, one at a time, and an open answer window is never
    interrupted. An approval that outlives its window is announced: "docs approval moved to your
    screen."
  - Sessions that finish are announced in chatty mode, and finishes within 10 seconds are said
    together ("api and docs finished").
  - At most one unrequested announcement every 20 seconds; one that waits two minutes is dropped.
  - Modes: quiet (approvals only), focus (and failures; the default) and chatty (everything,
    with a briefing every five minutes while something is running).
  - `earshot mode NAME` and `earshot status` reach the running daemon through a new `Command`
    message on its socket, with the same token. A command only changes announcements; it can't
    answer a request.
- Push-to-talk (Phase 4, milestone 3). A press of the AirPods stem, or `earshot talk`, plays the
  listening tone and hears one command: status, repeat, details (the waiting request, its
  critical fields letter by letter), stop, or a mode name. Nothing said in that window can
  approve or deny a request, and it never opens over an answer window.
  - `earshotd --stem` makes the helper the "Now Playing" app so the press reaches it (D-032);
    while it runs, the stem no longer plays or pauses music.
- The risk-gate interface (Phase 4, milestone 4), `policy/risk.py`. A gate's `score()` gives a
  number from 0 to 1 and reason codes; 0.5 raises a request to tier 2 and 0.85 to tier 3, and
  the final tier is the higher of the rules' and the gate's. A gate can never lower a tier, a
  gate that fails, hangs (300 ms) or returns nonsense changes nothing, and reasons are spoken
  only from a closed list ("Raised, for secrets nearby."). No gate ships in 1.0.
- The audit chain is anchored (Phase 4, milestone 5; P-10's second half). After every record,
  the chain's head and length are saved outside the log: in the Keychain on a real install, in
  a 0600 file beside the key in development. `earshot audit verify` and `earshot doctor` now
  catch records cut off the end, an older copy of the log put back, and records written while
  the daemon wasn't running.
- The red-team suite (Phase 4, milestone 6), `tests/redteam/`, run with every `pytest`:
  injection strings, lookalike packages, pushes to main, hidden and destructive commands, tier 3
  with every reply, replays, splices, other voices, forged socket messages and tampered audit
  logs. `docs/redteam.md` lists each attack, what stops it, and the result. It found four gaps,
  all fixed (below). `dev/redteam_replay.py` plays your own recordings at Earshot on the Mac.
- The soak tool and the gate session (Phase 4, milestone 7). `dev/soak.py` samples the daemon's
  and the helper's memory and CPU every minute for hours and counts reconnects, tracebacks, nods
  seen inside answer windows and every decision from the log. `docs/phase-4-gate.md` is the
  session on the Mac. `earshot service install` takes `--helper` and `--stem`.
- With nods off, a nod inside an answer window is still logged as seen (once per window), so
  the soak can count false nods without any of them approving anything (D-018).
- `dev/gate_voice.py`: the Phase 4 gate's voice runs, guided by a voice in the AirPods and
  checked from the daemon's log, with PASS or FAIL per run. It replaces step 3's table of runs to
  time by hand, which at the gate kept answers landing before the tone.

### Changed

- Found by the red team: a shell given a program made at run time (`bash -c "$(…)"`), and code
  given to an interpreter inline (`python -c`, `node -e`, `ruby -e`, `perl -E`), are tier 3,
  since they can't be read. They were tier 2.
- The challenge word `sphinx`, misheard twice at the Phase 2 gate (D-030), is replaced by
  `wilderness`.

- Phase 3 (the summarizer) is postponed, and Phase 4 takes the 0.3.x releases (D-031).
  `docs/phase-4-plan.md` is its plan. Push-to-talk will be the AirPods stem, and no voice-clone
  model is used (D-032).

### Fixed

- Found at the Phase 4 gate: the helper's mic didn't start with the AirPods in use (push-to-talk
  heard 0 frames). It captured through `AVAudioEngine`, which won't start when the AirPods'
  output runs at 48 kHz and their mic at 24 kHz (error -10868). It now captures input only,
  through `AVCaptureSession`, which delivers 16 kHz mono itself (D-033).
- `earshot talk` gave up after 5 seconds, before the daemon's listening window and reply were
  done, and said the daemon wasn't running. It now waits up to 40 seconds for `talk` (and still 5
  for `mode` and `status`).
- Found at the Phase 4 gate: a long question could go silent after its last word for up to
  minutes (191 s once), until you spoke or the request timed out, and nothing else was said
  meanwhile. Kokoro makes a tier-2 question's four clauses at once, filling the speech queue,
  and the end marker gave up after a second and was lost. It now waits for room like a clause.
  The clause's audio is also made under the MLX lock now, and a stall over 15 s logs every
  thread's stack.
- The listening tone came 0.5–1 s after the question, on top of your answer, so the answer was
  thrown away as begun too early. Every piece of a sentence (chime, clauses, tone) was its own
  stream, and each new stream on the AirPods took that long to start and could clip a piece's
  edges. A sentence now plays through one stream, a question ends with the tone right after its
  last word, and the window opens when it has played (D-034).
- Pressing the AirPods stem while Earshot's mic was open put "Cannot Control Mic with AirPods" on
  screen: with the mic open, a press is macOS's mute gesture, and an app that captures must
  handle it. The helper now does, and never mutes; with `--stem` the press is passed on like any
  other, and the daemon still ignores presses during an approval (D-032, D-033).
- An unanswered approval kept the floor through its minute-long holds between asks (up to four
  minutes), so for that time the stem did nothing, `earshot talk` was refused, other approvals
  waited, and "details", which spells out a waiting request, could never run. The floor is now
  free while it holds; the approval takes it back in turn to ask again (D-035).
- A noise in the answer window could make Earshot say "Wait for the tone, then …" with nobody
  speaking. A sound that seemed to begin before the window was refused as cut off before Silero
  was asked whether it was speech, and after an ignored noise the noise's own tail counted as
  "before the window". Now only speech counts as cut off, and only sound from before the tone
  does (D-036). Speech begun before the tone is still never parsed.

## [0.2.0] - 2026-11-11

### Added

- The policy engine (Phase 2, milestone 1). Every request gets a tier from rules alone:
  - a default per tool
  - the spec's example rules, built in
  - your `~/.earshot/policy.yaml`
  - a repo's `.earshot/policy.yaml`, which can only raise tiers until trusted (P-11)
  - minimums and a never-by-voice floor that no file can lower

  `earshot policy check` prints the tier a saved request would get and why.
- Resolvers (Phase 2, milestone 2). A Bash command is split into the commands it runs, and each is
  judged on its own:
  - Wrappers are seen through, and `sh -c` is parsed in turn.
  - Git aliases are expanded, and a push's real target is read from the repository. A bare
    `git push` on `main` is tier 3.
  - Recursive deletes, deploys, piping into a shell, and anything that can't be read statically
    are tier 3.
  - Once build or test config is edited in a session, later commands are at least tier 2 (P-01).

  `hypothesis` joins the dev tools, for property tests that disguise dangerous commands.
- Critical fields and the fidelity checker (Phase 2, milestone 3).
  - Each request's critical fields come from the policy engine's reading: the branch a push
    really sends, every package and version, the file and folder, delete targets, and a network
    call's domain and method.
  - The narrator says one clause per command, and the checker refuses any sentence that drops a
    field or invents a word. A refused sentence sends the request to the screen.
- `earshot test --tier 2` tries a challenge word and the voiceprint. `earshot enroll --record
  NAME` records phrases for calibration only. `docs/phase-2-gate.md` is the Mac session that runs
  Phase 2's gate.
- The signed helper, `earshot-motion` (Phase 2, milestone 7).
  - It's a small Swift app that captures the AirPods mic (so macOS grants the mic to it, once),
    streams head motion, and reports device changes, over a private, token-checked socket.
  - `earshotd --voice --helper PATH` uses it. A shake hands a request to the screen.
  - Nods stay off unless `--nods`, and then need a strict double nod, at tier 1 only (D-018).
  - `dev/count_false_nods.py` runs the hour-long count.
- The voiceprint (Phase 2, milestone 6).
  - ECAPA runs on onnxruntime, with its features computed in numpy, so the daemon needs no
    PyTorch. They match SpeechBrain's to a cosine of 1.000000.
  - `earshot enroll` records 12 phrases through the AirPods, plus 6 held out, and keeps only a
    private template.
  - Tier 2 needs a match. Every answer's score goes to the audit log.
  - `dev/export_ecapa.py` makes the model, and `dev/calibrate_voiceprint.py` sets the threshold
    from other voices (Q-5). onnxruntime (MIT) joins the voice group.
- Challenge words for tier 2 (Phase 2, milestone 5).
  - 200 words, pronounceable by Kokoro, no two within one Double Metaphone edit (P-08).
  - A tier-2 request asks "To install, say: approve harbor." It's approved only when the reply
    ends with the word and the voiceprint matches, and a plain "yes" never answers it.
  - Until a voiceprint is enrolled, tier 2 stays on the screen. `metaphone` (BSD) is a new
    dependency.
- Lookalike packages (Phase 2, milestone 4), with P-09's thresholds.
  - An install of a name close to a popular PyPI or npm package, but not on the list, is tier 3,
    spelled out, and said as "which looks like requests".
  - The lists ship in the package and are refreshed at release time
    (`dev/refresh_package_lists.py`).
- Redaction knows more token formats (GitLab, Stripe, Google, SendGrid, npm, PyPI, Hugging Face,
  Twilio), and secrets named by assignments and `--password` options. A corpus test covers it. `earshot policy
  trust` lets a repo's policy lower tiers until the file changes. PyYAML is a new dependency.
- The Phase 2 plan (`docs/phase-2-plan.md`): nine milestones in build order, the gate's targets
  and how each is measured, and the decisions each milestone needs. rehaan accepted the five
  proposals due before Phase 2 (P-01, P-02, P-08, P-09, P-11) as D-029.
- `dev/false_approvals.py`, the recorded-audio check for false approvals, run by hand on the Mac
  (D-023). It sends Step 0's recordings through the daemon's own listening path.
- A short listening tone marks when to answer. An answer begun before it is never parsed, and
  Earshot asks you to wait for the tone (D-028).
- `earshotd --keep-audio` saves each reply's clip in the home's `audio/` folder, with what VAD
  and the recognizers made of it, to tune listening on real failures (P-20). It's off by
  default, since audio isn't stored.

### Changed

- Parakeet and Whisper run at 8 bits (Phase 2, milestone 8).
  - Earshot's footprint falls from 3.2 GB to 1.7 GB, or 2.8 GB with Whisper loaded, under the
    spec's 3 GB.
  - On Step 0's recordings, 8-bit Parakeet hears 109 of 110 replies word for word as before.
- Speech starts sooner. Kokoro speaks clause by clause, and makes each clause while the chime or
  the last one plays. The first word arrives in about 0.6 s, where it took 1.1 s.
- The hook sends an edited file's path with PostToolUse, so the daemon knows when build or test
  config changed.
- The voice decider, the audit log and observe mode take tiers from the policy engine, in place
  of Phase 1's safety stub. Voice still approves only tier 1. Tier 2 joins once challenge words
  and the voiceprint are in. Reads inside the project are now tier 1, where the stub sent them to
  the screen.

### Fixed

- Barge-in stops Earshot only when Silero hears speech. It used to fire on any sound over 0.05,
  and in a live check a noise in the room, or a click as the AirPods switched into headset mode,
  cut most questions off within a second or two, before anything could be heard.
- Found by the red team: a backslash-newline inside a word (`git\⏎ push`) is joined as the
  shell joins it, so the command is judged as a push; and the decider never parses a cut-off
  reply's transcript, at any tier (the live path never gave it one, so it couldn't be reached).
- Noise and cut-off replies are no longer heard as approvals (P-20, D-027).
  - Silero VAD must hear speech in a reply before Parakeet does.
  - A reply that began before the listening window, for example while you talked over Earshot,
    is never parsed; Earshot asks again.
  - On Step 0's recordings, Parakeet alone approved 38 of 134 room-sound clips and 139 of 1,297
    cut-off non-approvals. Now none get through, and every real approval is still heard.
  - A live check with the AirPods still found one false approval: VAD dropped a short "no", then
    let a faint sound through that Parakeet heard as "Yeah.". P-20 stays open, and voice is for
    a scratch project only.
- The helper's first run on the Mac, at the Phase 2 gate session (11 Nov):
  - `earshotd --helper` with a relative path couldn't open the app; every path is now absolute.
  - Earshot heard nothing through the helper: it sends 100 ms of audio at a time, and the
    endpointer was tuned on 20 ms frames. Its audio is now cut into 20 ms frames, timed by their
    samples.
  - The helper asks for motion when it starts, so the prompt doesn't arrive mid-request, and
    starts the mic again if the audio setup changes. Its notes reach the daemon's log.
  - Its hello now always goes first; a permissions message could beat it, and the connection was
    refused until the retry 2 seconds later.
  - `earshot enroll --helper APP` records through the helper, the same channel the daemon checks
    the voiceprint on.
- `earshot test` used a random folder name, which Earshot spelled out letter by letter, so tier-2
  questions took up to 23 seconds and answers came before the tone. It's now "earshot test", in a
  new session each run, and the folder is removed afterwards.
- The daemon logs how long each question took to say, and a late listening tone.
- Phase 2 passed its gate (D-030), with deferrals: friends' calibration, the hour-long nod count,
  a longer stretch of use for P-20, and the helper's fixed signature.

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

[Unreleased]: https://github.com/rk-python5/Earshot/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/rk-python5/Earshot/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rk-python5/Earshot/compare/v0.0.2...v0.1.0
[0.0.2]: https://github.com/rk-python5/Earshot/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/rk-python5/Earshot/releases/tag/v0.0.1
