# Phase 4 plan: sessions, the risk gate and hardening

Phase 2 made one voice conversation safe. Phase 4 makes Earshot dependable with several Claude
Code sessions at once, and then tries to break it. This is the build plan's "week 7", and its
**gate is one rule: the red-team suite gets no approval through.** Phase 3 (the summarizer) is
postponed (D-031), so the releases are `0.3.x`.

**Gate:** every attack in the red-team suite ends on the screen, the 8-hour soak shows no
growth or crash, and the Mac checks below pass. When it passes, record it in `decisions.md` and
release 0.3.0 (D-006, D-031).

Keep this file current: mark a milestone done in the same commit that finishes it.

## Scope

From the build plan's Phase 4 list:

- the session registry with chimes, and `Stop` and idle events
- the floor manager: priorities, batching, modes, briefings and push-to-talk commands
- the risk-gate interface (`score()`), the higher-tier merge, and spoken reasons
- the red-team run and fixes, and the 8-hour soak

Moved here by decisions:

- anchoring the audit chain's head outside the file (D-025, P-10's second half)
- the hour-long nod count and a longer stretch of voice use for P-20 (D-030), both of which the
  soak covers
- friends' phrases to calibrate the voiceprint (Q-5, D-030), which the red team needs anyway
- the LaunchAgent's checks at login (Phase 1's milestone 8)

Not in Phase 4:

- the summarizer and EarshotBench (postponed, D-031)
- a gesture classifier (v2), because there is no training data; the thresholds ship (D-018)
- a replay-and-clone detector, and a voice-clone test (D-032); both are research items after 1.0
- packaging and launch (Phase 5)

## What already exists

- **Sessions:** `SessionStart` registers a session, named after its folder, with one of eight
  chimes. `SessionEnd` removes it, and `Stop` keeps the last message. Several sessions share one
  floor lock in the voice decider, and the queue count is spoken ("2 more waiting").
- **What's missing:** nothing speaks unless a request is waiting. Nothing knows if a session is
  running, waiting or finished. There are no modes, no briefings and no commands. An approval that
  times out says nothing.

## Milestones

In build order. "Code" means Claude builds and tests it; "Mac" means it needs rehaan, the
AirPods, friends or hours of wall time.

| # | Milestone                                          | Where     | Rests on          | Status |
| - | -------------------------------------------------- | --------- | ----------------- | ------ |
| 1 | Session activity and briefings                     | Code      | D-020             | Done   |
| 2 | The floor manager, modes and announcements         | Code      | D-031, D-032      | Done   |
| 3 | Push-to-talk: the stem, `earshot talk`, commands   | Code, Mac | D-016, D-032      | Code   |
| 4 | The risk-gate interface                            | Code      | the spec          | Code   |
| 5 | Anchoring the audit chain                          | Code      | D-025, P-10       | Code   |
| 6 | The red-team suite                                 | Code, Mac | D-030, D-032      | Code   |
| 7 | The soak tool, loose ends and the gate session     | Code, Mac | —                 | Code   |
| 8 | The gate                                           | Mac       | —                 | Ready  |

### 1. Session activity and briefings (code)

- Each session records what it is doing: working (since when, and how many tools it has run),
  finished (when), or idle. A `PostToolUse` means working, `Stop` means finished, and Claude
  Code's idle notification marks it idle. A session with a waiting request is "waiting for you".
- `daemon/briefing.py` builds the answer to "What's everyone doing?" from the registry: under 15
  seconds when spoken, for example "Three sessions. API: running 12 minutes, 14 tools run. Docs:
  waiting for you. Deploy: finished 5 minutes ago." More than five sessions end with "and two
  more". No file contents or messages are read aloud.
- **Done when:** unit tests cover each state and the length cap.

### 2. The floor manager, modes and announcements (code)

- **`daemon/floor.py`** owns who speaks. One voice, in this order:
  - **P0 approvals** that block an agent. One is open at a time and the rest queue ("two more
    waiting"). An open answer window is never interrupted.
  - **P1 failures:** an approval that outlived its window, "Docs approval moved to your screen."
  - **P2 a session finished,** batched: finishes within 10 seconds merge ("API and docs
    finished").
  - **P3 progress,** only inside briefings, never on its own.
- At most one unrequested announcement every 20 seconds. A stale one (two minutes old) is dropped.
- **Modes:** quiet (approvals only), focus (approvals and failures; the default), chatty
  (everything, with a briefing every five minutes while something is running).
- **Control:** `earshot mode NAME`, `earshot status` and `earshot talk` reach the running daemon
  through a new `Command` message on the same socket, token and contract rules. This is the one
  addition to the five messages, and it only changes announcements: no command can approve a
  request.
- `VoiceDecider` takes the floor from the manager in place of its own lock.
- **Done when:** unit tests cover the order, the 20-second gap, the batch, the stale drop and each
  mode, with a fake voice and a fake clock.

### 3. Push-to-talk (code, then Mac)

- **The press:** the helper registers the play/pause media commands (D-032) and sends `{"button":
  "stem"}`. `earshotd --stem` starts it that way. `earshot talk` sends the same trigger.
- **The window:** a press takes the floor (it cuts off an announcement but never an open answer
  window), plays the listening tone, and listens for one command. A shake of the head cancels.
- **Commands in v1.0:** `status` (the briefing), `repeat` (the last thing said), `details` (spell
  out the current request), `stop` (silence and clear the queue), and the three mode names, with
  or without "mode" ("Earshot, quiet mode"). Anything else gets "Sorry, I didn't catch that."
- **No command approves anything.** The window never parses yes or no, and an open approval is
  never answered from here.
- **Left for the Mac:** the stem press itself, which needs the AirPods and may need changes once
  seen on hardware (the fallback is `earshot talk`).

### 4. The risk-gate interface (code)

- `policy/risk.py`: a gate has a `score(request)` that returns a number from 0 to 1 and reasons.
  The score maps to a tier, and **the final tier is the higher of the rule tier and the gate's.**
  A gate that fails, hangs or isn't there changes nothing. Nothing can lower a tier, and tier 3
  stays tier 3.
- Spoken reasons come from a closed list of phrases. Anything a gate writes outside that list is
  logged and not spoken, so a model can't talk through the speaker.
- No gate model ships in 1.0. This is the interface and its tests, as the spec asks.
- **Done when:** property tests show the merge never lowers a tier.

### 5. Anchoring the audit chain (code)

- The chain's head and record count are stored outside the log: in the Keychain on a real install,
  in a 0600 file in development, the way the key already is. `earshot audit verify` now catches
  records cut off the end, which a hash chain alone can't.
- **Done when:** tests cut, edit, reorder, forge and replace a log, and each is reported.

### 6. The red-team suite (code, then Mac)

- **Automated, in CI** (`tests/redteam/`, marker `redteam`, part of every `pytest` run):
  - prompt-injection strings in commands, file names, contents, URLs and folder names: the tier
    never drops and the narrator reads them literally
  - lookalike packages, a bare `git push` on `main`, and obfuscated shells: all tier 3
  - tier 3 by voice, with every possible reply
  - a replay of an old challenge word, a plain "yes" at tier 2, a long recording with the word
    spliced in, a voiceprint mismatch, a cut-off reply, and a nod at tier 2
  - a forged socket message, a wrong token, an oversized line, and an event meant to cancel
    someone else's request
  - edited, deleted, reordered, forged and truncated audit logs
- **On the Mac** (`docs/phase-4-gate.md`):
  - other people's voices saying the right challenge word: friends, which also finishes Q-5
  - your own recordings played back through a speaker (`dev/redteam_replay.py`)
  - the disguised voice, already measured at the gate (D-030)
- `docs/redteam.md` lists every attack, what stops it, the test, and the result. A clone of your
  voice is a stated limit, not a test (D-032).
- **Done when:** every attack ends on the screen. A single approval blocks the release.

### 7. The soak tool, loose ends and the gate session (code)

- `dev/soak.py` samples Earshot's memory and CPU every minute for the length of the soak, counts
  false nods and helper crashes from the log, and says whether memory grew.
- `docs/phase-4-gate.md` is the session on the Mac, with each command explained.
- Loose ends: replace the challenge word `sphinx`, which two recognisers misheard (D-030).

### 8. The gate (Mac)

| Target                                  | Measured by                                              |
| --------------------------------------- | -------------------------------------------------------- |
| Tier 3 by voice: never                  | the red-team suite                                       |
| No attack gets an approval              | the red-team suite, and the Mac attacks                  |
| Impostors at tier 2 ≤ 2%                | friends' phrases, calibrated (Q-5)                       |
| False nods ≤ 1 an hour                  | the soak, with nods switched on for it                   |
| No growth or crash over 8 hours         | `dev/soak.py`: memory, CPU and crashes                   |
| No false approvals                      | `dev/false_approvals.py`, and the soak's kept audio (P-20) |
| Announcements obey the floor            | a live check of each mode and a briefing                 |
| The stem starts push-to-talk            | a live check, or `earshot talk` if the stem can't        |

## Decisions Phase 4 needs

| Needed before | Item                                            | Status              |
| ------------- | ----------------------------------------------- | ------------------- |
| Milestone 1   | Phase 3 skipped; version numbers                | Accepted as D-031   |
| Milestone 3   | How push-to-talk starts                         | Accepted as D-032   |
| Milestone 6   | A voice-clone test                              | Skipped (D-032)     |
| Gate          | P-22, the choices made while building           | Open                |

## Where things live during development

As before: libraries and models stay inside the repo (D-013), data under `.tools/earshot/`, and
hooks only in `~/earshot-scratch`. The soak runs real sessions there.

## Testing

- **CI, on every push:** unit tests for the floor, modes, briefings, commands, the gate merge and
  the anchor, and the whole red-team suite.
- **rehaan's Mac:** the gate session, and the recorded-audio checks by hand after any change to
  the listening path (P-14 is deferred).
