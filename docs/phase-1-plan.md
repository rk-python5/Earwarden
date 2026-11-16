# Phase 1 plan: the walking skeleton

Phase 1 turns the Step 0 spikes into a thin Earshot that works end to end. Claude Code asks for
permission, Earshot speaks the request in your AirPods, you answer, and Claude Code gets the
decision. This is the build plan's "weeks 2–3", plus what the Step 0 gate added (D-014 to D-018).

**Gate:** a real Claude Code session on rehaan's subscription, approved by voice end to end. Run it
in a scratch repo. When it passes, record it in `decisions.md` and release 0.1.0 (D-006).

Keep this file current: mark a milestone done in the same commit that finishes it.

**Changed 4 Nov (D-023):** the observe week is optional. In Phase 1 the daemon captures the mic
itself (the helper app's audio half moves to Phase 2) and ends speech by energy (Silero VAD in
Phase 2). The recorded-audio test runs by hand on the Mac.

## Scope

From the build plan's Phase 1 list:

- `contracts.py` with all five messages, and the daemon's socket server with a token check
- `earshot-hook` (standard library only), with every fail-safe path tested
- `earshot init` and `earshot uninstall`, editing Claude Code's settings with a backup
- the template narrator for the six action families, and the spoken-form normaliser
- speech out (Kokoro and chimes) and speech in (voice detection and recognition), with answer
  windows
- intent rules (yes, no, wait, instruction) and the deny-message path
- presence routing: keyboard idle time and the output device
- the hash-chained audit log and `earshot audit verify`
- the LaunchAgent and `earshot doctor`
- the first end-to-end test with a fake Claude Code

Added by the Step 0 gate:

- the answer-window guards (D-015)
- the helper app's mic capture and device changes (D-016)
- two-stage recognition, Parakeet then Whisper (D-017)
- three costs carried over from Step 0: Kokoro's first audio (237 ms against a 200 ms budget),
  Whisper's 1.2 s second listens, and memory

Not in Phase 1, which waits for Phase 2 or later:

- the policy engine, resolvers and lookalike checks
- critical-field extractors and the fidelity checker
- challenge words and the voiceprint
- the nod detector
- the floor manager's modes and briefings, and push-to-talk
- the summarizer model

## A safety stub until Phase 2 (D-019)

Phase 1 speaks requests and accepts "yes", but the rules that keep tier 3 away from voice only
arrive with Phase 2's policy engine. Until then, a stub applies (D-019, from P-19):

- **Voice approves only an allowlist:**
  - file edits and writes inside the session's folder, except in `.git/`, `.claude/`, `.earshot/`,
    `.github/workflows/` and `.envrc`, and except build and test config (`conftest.py`,
    `package.json`, `Makefile`, `pyproject.toml`, `setup.py`)
  - single test commands (`pytest`, `uv run pytest`, `npm test`), with no chaining, pipes or
    redirection
- **Everything else goes to the screen.** With voice on, Earshot says so briefly ("API needs you;
  it's on your screen") and doesn't listen.
- **Secrets are redacted** by pattern before anything is spoken or logged.

## Milestones

In build order. "Cloud" means Claude builds and tests it in a cloud session. "Mac" means it needs
rehaan's Mac and AirPods.

| # | Milestone                                  | Where           | Rests on     | Status                    |
| - | ------------------------------------------ | --------------- | ------------ | ------------------------- |
| 1 | Contracts and the hook client              | Cloud           | D-019, D-020 | Done                      |
| 2 | The daemon core                            | Cloud           | D-020        | Done                      |
| 3 | Install, uninstall and observe mode        | Cloud, then Mac | D-021        | Built; observe week next  |
| 4 | Narrator v0 and redaction                  | Cloud           | D-022, D-024 | Done                      |
| 5 | Speech out and speech in                   | Mac             | D-022, D-023 | Done                      |
| 6 | Intent, presence and the decision path     | Cloud           | D-024        | Done                      |
| 7 | The audit log                              | Cloud           | D-025        | Done                      |
| 8 | The helper app, the LaunchAgent and doctor | Mac             | D-023        | LaunchAgent unchecked     |
| 9 | End to end, and the gate                   | Cloud, then Mac | —            | Done                      |

### 1. Contracts and the hook client (cloud)

- `src/earshot/contracts.py`: the five messages (ApprovalRequest, Assessment, Decision, Event,
  AuditRecord) as Pydantic models at version 1, validated at every hop. Anything unrecognised
  becomes a hand-off to the screen. Pydantic is the first runtime dependency.
- `earshot-hook`, grown from the Step 0 probe:
  - It reads Claude Code's JSON and sends an ApprovalRequest over the socket with the token.
  - It waits up to the hand-off limit, then prints one decision object or nothing, and always
    exits 0.
  - `--event` sends events without waiting. D-020 adds `PostToolUse` to them.
- Tests: every fail-safe path, run as a real subprocess:
  - no daemon, a missing token, a wrong token
  - malformed or oversized input
  - a daemon that hangs, SIGTERM, a socket closed early
  - an outcome the hook doesn't know

  Contract tests replay payloads captured from Claude Code 2.1.318. The Step 0 probe logged
  them on rehaan's Mac.
- **Done when:** those tests pass in CI, and a round trip against a stub daemon stays within the
  plan's 80 ms on the Mac.
- **Done (4 Nov):** the contracts, `wire.py` and `paths.py`, and `earshot-hook`. All 214 tests
  pass on rehaan's Mac. The round trip against a stand-in daemon took **21 ms median (max 24 ms)
  on the Mac**, against the plan's 80 ms, and 38 ms in the cloud container.
- **Found in the payloads:** Claude Code 2.1.318 sends a `prompt_id` with every event, shared by
  a request and its `PostToolUse`. The hook passes it on, and fingerprints the tool input of a
  `PostToolUse`, so milestone 2 can match the two (D-020).

### 2. The daemon core (cloud)

- `earshotd`: one asyncio process. It speaks newline-delimited JSON over a Unix socket with mode
  0600, checks a random token kept in a 0600 file, and never opens a network port.
- A registry of pending requests: a decision must match a waiting hook's id.
- Sessions: registered by SessionStart, updated by Stop, removed by SessionEnd. Any request from
  an unknown session registers it on the spot (D-020).
- Lifecycle (D-020): a `PostToolUse` for a pending request means you approved it on screen, and a
  closed hook socket means you pressed No or Esc. Either cancels the voice prompt.
- At this stage every request goes to the screen. The voice path plugs in at milestone 6.
- **Done when:** tests cover the protocol, token rejection, three sessions at once, both kinds of
  cancellation, and a killed daemon (the hook prints nothing).
- **Done (4 Nov):** `earshotd` and its 47 tests, all with the real hook. They cover the cases
  above, a session ending, the wait limit, a failing or confused decider, stopping, a second
  daemon, and a socket left by a crash. A request that arrives while the daemon stops goes to
  the screen.
- **Found:** in Python 3.11, closing an asyncio server while it's accepting a connection drops
  that connection without closing its socket. The daemon now stops accepting and lets accepted
  connections finish before closing the server, and a test guards it.

### 3. Install, uninstall and observe mode (cloud, then a week on the Mac)

- `earshot init` backs up Claude Code's settings and adds Earshot's hooks next to any you already
  have. It also creates the config and the token. `earshot uninstall` removes only Earshot's
  entries.
- Observe mode (D-021): for each request, the daemon logs the permission mode, the tool, and the
  tier the stub would give it, then hands the request to the screen. It never answers.
- **Mac:** run observe mode in the background through a week of normal work, while milestones 4
  to 7 are built. It counts how many prompts reach Earshot per hour under auto mode, and supplies
  real payloads for the tests.
- **Done when:** an init-then-uninstall round trip leaves the settings file byte-for-byte as it
  was, tested with temporary home folders, and the week's counts are written up.
- **Built (4 Nov):** `earshot init`, `earshot uninstall`, `earshot observe` (the week's summary),
  `earshotd --observe`, and the safety stub (`stub.py`, D-019) whose verdict observe mode logs.
  The log holds the time, session, permission mode, tool and verdict, never command text or file
  contents. The commands use argparse for now rather than the spec's Typer and Rich, to keep
  dependencies down until the CLI grows.

### 4. Narrator v0 and redaction (cloud)

- Templates for the six action families (git push, package install, file write or edit, delete,
  network call, MCP tool), plus a generic fallback.
- The spoken-form normaliser, from the plan's table: `feature/login-v2` becomes "feature slash
  login v2", and so on. The 25-word length rule applies.
- Secret redaction by pattern, before anything is spoken or logged (D-019). Phase 2 adds entropy
  detection and the fidelity checker.
- Pronounceability (P-03): every word must get phonemes from Kokoro's front-end (D-022), or be
  spelled out letter by letter. misaki runs on any OS, so CI checks it.
- **Done when:** there are golden tests for each family, the plan's normaliser examples pass,
  and no word is silent on the Step 0 identifier lists.

### 5. Speech out and speech in (Mac)

- **Out:**
  - Kokoro through the D-022 front-end, streamed sentence by sentence.
  - Chimes synthesised in code.
  - Before every utterance, a check that the AirPods are the output.
  - Work on the 237 ms first audio.
- **In:**
  - Answer windows of 8 s with one re-ask, and the mic kept warm while an approval is pending
    (Q-2).
  - Silero voice detection: an answer ends after 400 ms of silence, or at 6 s. Pre-roll never
    reaches back before the window opened (D-015).
  - Barge-in: talking while Earshot speaks stops playback.
  - Two-stage recognition (D-017). An answer that's still unclear is asked once more, then goes
    to the screen.
- Audio capture sits behind one interface: sounddevice inside the daemon for now, and the helper
  app from milestone 8.
- Memory: try 8-bit Parakeet, 4-bit Whisper, and loading Whisper only when it's needed.
- **Done when:** on the Mac, a scripted approval is spoken in the AirPods and hears "yes", "no"
  and an instruction correctly, with per-stage timings logged. The 100 Step 0 recordings run
  through voice detection, recognition and intent; P-14 decides where that test runs.
- **Done (8 Nov):**
  - On the Mac, `earshot test` heard "approve", "no" and "no, call it readme instead" correctly,
    with speaking and recognition times in the audit log and listen levels in the daemon's log.
  - The recorded-audio test waits for P-14 (deferred by D-023).
  - Running the recordings by hand found P-20: non-speech and cut-off replies can be heard as
    approvals. That's the first fix in Phase 2.
  - Silero VAD and the memory work moved to Phase 2 (D-023). Kokoro's first audio is 195–409 ms
    (D-026).

### 6. Intent, presence and the decision path (cloud)

- Intent rules for yes, no, wait and instruction, starting from `spikes/speech/speech_data.py`,
  whose rules are already tested against every recorded label. They include P-07's exact
  whole-utterance match and P-16's rule that an answer goes to the one open approval. A deny
  carries its message back to Claude Code.
- Presence routing: voice only when the AirPods are the output and you've been away from the
  keyboard for 45 s, or voice is pinned on. Otherwise Earshot hands off at once.
- A minimal floor: one approval open at a time, and the rest queued ("two more waiting"). Modes
  and briefings wait for Phase 4.
- While you're away, Earshot holds and re-announces a prompt instead of handing off at 90 s
  (D-020).
- **Done when:** unit tests cover every intent label and the presence rules, with the system
  calls faked.

### 7. The audit log (cloud)

- One JSON line per decision, hash-chained, with `earshot audit verify` and `earshot audit tail`.
- P-10 decides whether the chain is keyed with a secret held in the Keychain and anchored outside
  the file.
- **Done when:** in tests, verify catches an edited, deleted or reordered line.

### 8. The helper app, the LaunchAgent and doctor (Mac)

- `src/earshot/helper_app/`, the signed helper app (D-016), in Swift:
  - It captures the AirPods mic, converts it to 16 kHz mono and streams it to the daemon.
  - It reports device changes, such as the AirPods connecting.
  - It's signed with a fixed identity, so permissions survive rebuilds.
  - Head motion stays in Phase 2.
- A LaunchAgent starts the daemon and the helper at login, and restarts them if they crash.
- `earshot doctor` checks the mic and motion permissions, the output device, the AirPods, the
  models, the socket and the hooks.
- **Mac setup:** full Xcode and a free Apple Development certificate (Xcode → Settings →
  Accounts), for the fixed signing identity.
- **Done when:**
  - macOS asks for the mic once, in the helper's name.
  - The grant survives a rebuild and a Python update.
  - A killed daemon restarts.
- **8 Nov:**
  - The helper app moved to Phase 2 (D-023).
  - `earshot doctor` ran on the Mac and found every piece.
  - The LaunchAgent now passes on `HF_HOME`, but it hasn't run on the Mac yet. Still to check: it
    starts at a real login, and it restarts a killed daemon.

### 9. End to end, and the gate (cloud, then Mac)

- A fake Claude Code replays captured payloads into `earshot-hook`, against a daemon with
  scripted audio, and checks the printed decision. Kill-the-daemon and slow-model tests sit
  alongside it. This runs in CI.
- `earshot test` runs one fake approval end to end on the Mac.
- **The gate:** a real Claude Code session, in a scratch repo, approved by voice end to end.
- **Then:** record the gate in `decisions.md`, and release 0.1.0.
- **Done (8 Nov):** the gate passed (D-026), and 0.1.0 was released.

## Decisions Phase 1 needs

| Needed before | Proposal                                          | Status                    |
| ------------- | ------------------------------------------------- | ------------------------- |
| Milestone 1   | P-12 lifecycle while the hook waits               | Accepted as D-020         |
| Milestone 1   | P-19 the safety stub                              | Accepted as D-019         |
| Milestone 3   | P-15 auto mode and observe mode                   | Accepted as D-021         |
| Milestone 4   | P-03 check that summaries can be spoken           | Accepted as D-024         |
| Milestone 4   | P-04 own the Kokoro front-end                     | Accepted as D-022         |
| Milestone 5   | P-14 recorded-audio tests on a self-hosted runner | Deferred by D-023         |
| Milestone 6   | P-07 approve only on an exact match               | Accepted as D-024         |
| Milestone 6   | P-16 don't route answers by session name          | Accepted as D-024         |
| Milestone 7   | P-10 a keyed, anchored audit chain                | Keyed chain, D-025        |

## Where things live during development

- Libraries, models and tools stay inside the repo (D-013).
- Earshot's own data (the socket, token, config and audit log) goes under `.tools/earshot/` in the
  repo, through an override. The plan's paths in `~/Library/Application Support/Earshot/` and
  `~/.earshot/` apply to real installs.
- Hooks go into a scratch project's `.claude/settings.local.json`, not your global settings.
  Observe mode is the one exception: it needs the global settings to see your normal sessions, so
  it's opt-in (D-021), with a backup that `earshot uninstall` restores.

## Testing

- **CI, on every push:**
  - unit and property tests: contracts, the hook's fail-safe paths, the socket protocol, settings
    editing, the narrator, intent rules and the audit chain
  - the end-to-end test with a fake Claude Code and scripted audio
- **rehaan's Mac, at each Mac milestone:**
  - speech with the real models and AirPods
  - a short hardware checklist
  - the 100 recorded replies (P-14)

## Running the gate (on the Mac)

1. `uv sync --group voice`, then
   `uv run earshot init --home .tools/earshot --settings ~/earshot-scratch/.claude/settings.local.json`.
   With the hooks in a scratch project, the Claude Code session you develop in isn't asked by
   voice.
2. `uv run earshotd --home .tools/earshot --voice --pin-voice` (pinned, because you'll be at the
   keyboard). The first run downloads the models.
3. `uv run earshot doctor --home .tools/earshot --settings ~/earshot-scratch/.claude/settings.local.json`,
   then `uv run earshot test --home .tools/earshot`: answer "yes" in the AirPods.
4. In a scratch repo, start `claude --permission-mode default` and ask it to edit a file. Answer
   "yes" by voice; then ask for a `git push` and check it's only announced.
5. `uv run earshot audit verify --home .tools/earshot` and `audit tail`.

When the edit is approved by voice end to end, record the gate in `decisions.md` and release
0.1.0. `earshot service install --home … --voice` makes the daemon start at login.

