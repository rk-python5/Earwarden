# Step 0 results and go/no-go note

Fill this in as the spikes run. The Step 0 gate: all four week-1 tests pass, written up with
numbers. When it passes, record it in `decisions.md`; Phase 1 starts after that.

The plan's four week-1 tests map to the sections below:

| Week-1 test                                 | Sections                           |
| ------------------------------------------- | ---------------------------------- |
| 1. Claude Code hook round trip              | 1                                  |
| 2. Speech in and out on the M2 with AirPods | 2, 3 and 4 (4 is a review addition) |
| 3. Head motion                              | 5                                  |
| 4. Voiceprint                               | 6                                  |

## Setup

| Item                             | Value |
| -------------------------------- | ----- |
| Date                             | 2026-11-04 (hook probe) |
| Mac (chip, memory)               | MacBook Air, M2, 16 GB (from the plan) |
| macOS version                    | 27.0.1 |
| Claude Code version              | 2.1.318 |
| AirPods model and firmware       | AirPods 4 (ANC), model A3055, firmware 9A348. They show up as "femida's AirPods - Find My", with separate input and output devices. |
| Earshot version / commit         | 0.0.2.dev0, commit c281407 (hook probe) |

## 1. Hook probe

Steps: [hook_probe/README.md](hook_probe/README.md).

| Check                                                    | Target                 | Result | Pass |
| -------------------------------------------------------- | ---------------------- | ------ | ---- |
| `allow` honoured, no dialog                              | yes                    | Yes. Run 2: "Allowed by PermissionRequest hook", no dialog, and the tool ran 59 ms after the decision. | Yes |
| `deny` honoured, the message reaches Claude              | yes                    | Yes. Run 3: no file was created. Claude quoted "Denied by the Earshot hook probe (Step 0 spike)" and stopped to ask how to go on. | Yes |
| No output brings up the normal dialog                    | yes                    | Yes. Run 1: the dialog appeared; approved on screen after about 11.7 s. | Yes |
| **Q-1:** dialog shown while the hook holds? (run 4)      | answer                 | **Yes, the dialog shows while the hook is still running.** Run 4 (`hold 30`): the tool ran 5.2 s after the hook started, because it was approved on screen, while the hook went on holding for the full 30 s. | —    |
| Late hook decision vs. an on-screen answer (run 5)       | answer                 | The on-screen answer wins. Retry: approved on screen at 2.5 s, and the hook's allow at 20 s was ignored. First attempt: No on screen ended the hook with SIGTERM before it could answer. | —    |
| How Esc ends a waiting hook (run 6)                      | answer                 | SIGTERM, and the tool doesn't run. | —    |
| `permission_prompt` notification during a hold (run 7)   | answer                 | Yes: it arrives 6.0 s after the request, even while the hook is still running (seen 3 times). Run 7 itself wasn't needed. | —    |
| Hook process start, median and p95 (`bench`)             | well under 80 ms       | 19.7 ms median, 24.6 ms p95 (18.1 ms fastest, 30 runs). That leaves about 55 ms of the plan's 80 ms for the socket round trip. | Yes |
| `PreToolUse` → `PermissionRequest` gap, median (`report`) | note                  | 39 ms median, 37–62 ms over 7 requests. Includes Claude Code's own permission check, starting the hook process and Python start-up. | —    |
| Decision → `PostToolUse` gap, median (`report`)          | note                   | 59 ms (run 2, the one immediate allow) | —    |
| Payload has the fields the plan's ApprovalRequest needs  | yes                    | Yes. `PermissionRequest` carries `session_id`, `cwd`, `permission_mode`, `tool_name` and `tool_input`. It also has `permission_suggestions`, `prompt_id`, `effort`, `scratchpad_dir` and `transcript_path`, but no `tool_use_id`. | Yes |

Notes:

- **First round:** the session started in Claude Code's auto mode (all 21 payloads said
  `permission_mode: auto`). Auto mode approved all seven `touch` commands itself, so no
  `PermissionRequest` reached the hook. The second round used `claude --permission-mode default`.
  This feeds P-15.
- **What Q-1 means for the design:** the dialog is always on screen, so a voice prompt never
  blocks someone at the keyboard. But the hook isn't told when you answer on screen. Approving
  lets the tool run while the hook keeps waiting; No or Esc end it with SIGTERM. This feeds P-12.
- **Other events:**
  - `Stop` carries `last_assistant_message`, which the plan uses for "finished" announcements.
  - `Notification` sends `idle_prompt` and `permission_prompt`.
  - `SessionStart` gives `session_id`, `cwd`, `model` and `source`.
  - `SessionEnd` gives a `reason`.
- Starting Python with `-I -S` (no site packages) didn't help: 22.0 ms median against 19.7 ms.
  The real hook doesn't need it.
- The raw log and sample payloads stay on the Mac, in `spikes/hook_probe/out/`.

## 2. Speech

Steps: [speech/README.md](speech/README.md).

| Check                                                        | Target                   | Result | Pass |
| ------------------------------------------------------------ | ------------------------ | ------ | ---- |
| Kokoro time to first audio, median and p95                   | ≤ 200 ms                 | 237 ms median, 384 ms p95 (30 sentences). It grows with the first sentence's length: 164 ms for a two-word sentence, about 370 ms for nine words. | No, but fixable |
| Kokoro real-time factor                                      | note                     | 0.104, about ten times faster than real time. The model loads in 0.8 s once cached. | —    |
| Kokoro peak memory                                           | about 0.2 GB             | 1.36 GB MLX peak (on an 11.6 s sentence), 0.78 GB process memory | No   |
| Parakeet yes/no correct, quiet                               | ≥ 98%                    | 16/19 (84.2%); with the silence trimmed, 17/19 (89.5%) | No   |
| Parakeet yes/no correct, noisy                               | ≥ 95%                    | 13/19 (68.4%); with the silence trimmed, 18/19 (94.7%) | No, nearly |
| Transcript exact, quiet and noisy                            | note                     | 29/50 (58%) quiet, 20/50 (40%) noisy. Intent correct: 35/50 and 28/50. | —    |
| False approvals, all 100 replies                             | 0                        | 0 | Yes  |
| Recognition time per reply, median                           | inside the 260 ms stage  | 90 ms median, 112 ms max | Yes  |
| Parakeet peak memory                                         | about 1.3 GB             | 2.60 GB MLX peak, 1.03 GB process memory, with the bf16 model (the plan assumed 8-bit) | No   |
| Confidence threshold: % of wrong caught, % of right re-asked | pick a threshold         | Weak separation: median lowest-word probability 0.597 when right, 0.375 when wrong. A 0.70 threshold catches 94% of wrong transcripts but re-asks 65% of right ones. | —    |
| Plan's Double Metaphone matcher on the decoys                | rejects them             | Rejected all 8, but mostly because the recogniser had already garbled the phrase. In noise, "approve orchid" came out as "Uproom orchard": the decoy word was heard as the real challenge word. | Yes, with a caveat |
| Words skipped without espeak-ng (`g2p_coverage.py`)          | none, after normalising  | 476 of the top 1,000 PyPI names (47.6%) and 48 of 87 identifiers have no phonemes; all come back when spelled letter by letter (measured 3 Nov 2026). On the Mac, turning the fallback off made sentence 01 0.5 s shorter (5.7 → 5.2 s): "quickstart" was dropped. | No: needs P-03 |

Notes:

- **First recognition run (4 Nov 2026), and why it misses so much.** The decoy lines show two
  causes:
  - A bare "yes" came back as an empty transcript, in both rooms.
  - "approve lantern" was heard as "Approved Lantern" or "A proof lantern", so the exact-phrase
    rule rejected genuine answers.

- **Diagnosis run (4 Nov 2026), with every miss listed:**
  - **Silence caused the empty answers.** With the full 3-second window, 18 short replies came
    back empty: yes, yep, nope, wait, later, cancel, deny, status, repeat, details, sure, hmm, and
    "docs, no". With the silence trimmed, as the voice detector will, only a bare "yes" came back
    empty, once in each room. Yes/no accuracy rose to 89.5% quiet and 94.7% noisy.
  - **The recogniser can't hear "approve", but it hears the challenge word.** In the trimmed run,
    "approve" came out right in only 1 of 20 genuine challenge replies. The rest were "Approved",
    "A proof", "A true", "A blue", "A broom", "A bro", "A drove" or "A Pro". The challenge word was
    right in 18 of 20; the misses were "harbor" heard as "Harvard" and "tunnel" as "or none", both
    in noise.
  - **What-ifs** (trimmed run; the second worked out by hand from the listed transcripts):
    - Counting "approved" and "a proof" as "approve" still misses 6 approvals in quiet and 7 in
      noise.
    - Letting the challenge word alone decide misses 2 in each room (the two above in noise; "API,
      yes" and the empty "yes" in quiet). It makes 1 false approval: in noise, the decoy "approve
      orchid" came out as "Atro orchard". That's only safe if no two challenge words sound alike,
      which P-08 already requires.
  - **The plan's matcher failed a decoy:** in the quiet trimmed run, "Approve orchid." was heard
    correctly, and the Double Metaphone matcher accepted it for "orchard". The strict rule refused
    it.
  - **Spoken session names are unreliable:** "docs" was heard as "dogs" (four times) and "API" as
    "A B I". See P-16.
  - **Other single words in noise:** "cancel" came out as "Dan said" and "later" as "Data."
  - **Confidence is still weak after trimming:** the median lowest-word probability was 0.687
    when right and 0.510 when wrong.

- **Recogniser comparison (4 Nov 2026):** the same 100 recordings, silence trimmed. "Word rule" is
  the challenge-word-alone what-if (P-08, revised).

  | Recogniser | Yes/no quiet | Yes/no noisy | False approvals, strict rules | Word rule: missed quiet / noisy, false approvals | Median time per reply | MLX peak |
  | --- | --- | --- | --- | --- | --- | --- |
  | Parakeet TDT 0.6B v2 | 17/19 (89.5%) | 18/19 (94.7%) | 0 | 2 / 2, 1 | 68 ms | 2.60 GB |
  | Parakeet TDT 0.6B v3 | 15/19 (78.9%) | 15/19 (78.9%) | **1** | 4 / 5, 1 | 68 ms | 2.64 GB |
  | Whisper large-v3-turbo | **19/19 (100%)** | 17/19 (89.5%) | 0 | 0 / 4, 1 | **1,135 ms** | 2.14 GB |
  | Moonshine base | 9/19 (47.4%) | 10/19 (52.6%) | 0 | 8 / 7, 0 | 33 ms | 0.32 GB |

  - **Parakeet v3 is ruled out.** It sometimes decided short English answers were Russian
    ("Штоп." for "stop", "Я." for "yeah", "Докс ну." for "docs, no"). It also heard the decoy
    "approve orchid" as "Approve orchard.", a false approval even under the strict rules.
  - **Whisper is the most accurate in quiet but about four times over the recognition budget.**
    It always encodes a 30-second window, however short the clip. It's also weaker in noise: "do
    it" became "Blink." and "status" became "Stryker.".
  - **Every model false-approved the same decoy under the word rule:** in noise, "approve orchid"
    came out ending in "orchard". Close-sounding words must stay out of the challenge list (P-08).
  - **Moonshine is ruled out.** It's fast and tiny, but it got only about half the yes/no
    answers. It doubled short answers ("Yes, yes.", "Go ahead go ahead") and sometimes looped
    until its token limit ("approve approve approve…", "knock, knock, knock…"), taking 1.1 s.
- **Two-stage recognition (`combine.py`):** the first recogniser hears every reply, and the
  second listens only when the first is unclear. Both are judged with P-07 and the challenge-word
  rule.

  | Setup | Yes/no quiet | Yes/no noisy | Approvals missed | False approvals | Second listens | Time per reply, median / p95 |
  | --- | --- | --- | --- | --- | --- | --- |
  | Parakeet v2 alone | 17/19 (89.5%) | 18/19 (94.7%) | 4 | 1 | — | 68 / 78 ms |
  | Whisper alone | 19/19 (100%) | 17/19 (89.5%) | 4 | 1 | — | 1,135 / 1,172 ms |
  | **Parakeet v2, then Whisper** | **19/19 (100%)** | **19/19 (100%)** | **0** | 1 | 23/100 | 70 / 1,217 ms |
  | Parakeet v2, then Moonshine | 18/19 (94.7%) | 18/19 (94.7%) | 2 | 1 | 23/100 | 70 / 107 ms |
  | Moonshine, then Whisper | 18/19 (94.7%) | 17/19 (89.5%) | 2 | 1 | 49/100 | 54 / 1,200 ms |

  - **Parakeet v2, then Whisper, meets the plan's yes/no targets** on these recordings, with
    nothing missed.
  - **Its one false approval is the deliberately confusable decoy** ("orchid" heard as "Atro
    orchard"), which a word list without close-sounding pairs rules out (P-08).
  - **Its other remaining mistake is "the docs one",** which P-16 removes.
  - **The costs:**
    - About 1.2 s on the 23% of replies that needed Whisper. The test set is heavy on challenge
      phrases and decoys, so real use should need it less.
    - Memory: both recognisers loaded at once is well over 3 GB unquantised.

  See P-17.
- **Safety held:** across 100 replies, including the negation traps, nothing that wasn't an
  approval was ever taken as one.
- **Kokoro's first sound:** a short first chunk fixes it, either by splitting the first sentence at
  a comma or by speaking a short lead-in. So does synthesising while the chime plays.
- **Memory is at risk.** The two MLX peaks add up to about 4 GB against the plan's 3 GB target.
  For Phase 1 to try:
  - the 8-bit Parakeet
  - an MLX cache limit
  - P-04's leaner text front-end. `misaki[en]` also pulled PyTorch into the voice's environment,
    as the warning at start-up shows.
- **Downloads:** the voice model was 355 MB. Its first load took 60 s including the download.

## 3. AirPods audio I/O

Steps: [audio_io/README.md](audio_io/README.md).

| Check                                                          | Target                         | Result | Pass |
| -------------------------------------------------------------- | ------------------------------ | ------ | ---- |
| **Q-2:** mic live after opening, median and max (`switch`)     | note; decides keeping it warm  | **847 ms median, 931 ms max** (5 trials). The stream starts in about 93 ms but delivers silence until the AirPods switch to headset mode. Long enough to clip an answer, so keep the mic warm. | —    |
| Output glitches when the mic opens                             | note                           | None reported by the output stream (0 in 5 trials) | —    |
| Output-to-mic delay (`leak`)                                   | note; sets the window guard    | Not measurable: the leak was too faint to correlate (correlation −0.21), so the 257 ms printed isn't reliable | —    |
| Leak gain and leak above the noise floor (`leak`)              | note; decides barge-in         | −55.6 dB gain, **16.7 dB below the room's noise floor**. The mic barely hears the AirPods' own playback, so barge-in works without echo cancellation or half-duplex. | —    |
| Self-approval, any guard, with and without pre-roll (`selfcheck`) | never approves              | None in 16 windows (2 prompts × 4 guards, with and without pre-roll), with the mic kept warm | Yes |
| Smallest guard where every window is quiet (`selfcheck`)       | pick it                        | 0 ms: no window held any of the prompt's speech | —    |

Notes:

- **Kept warm:** the self-approval check ran with the mic open the whole time, the way Earshot
  would keep it warm, so the Q-2 fix and P-06 were tested together.
- **A made-up "Mm-hmm.":** in one quiet window (tier 2, 500 ms guard, no pre-roll), Parakeet
  transcribed "Mm-hmm." from near-silence. It isn't an approval under the strict rules (P-07), but
  it shows two things: why recognition must sit behind voice-activity detection, and why fillers
  must never approve.
- **24 kHz input:** in headset mode the AirPods mic runs at 24 kHz (from the launchd run), and the
  plan's models expect 16 kHz, so Earshot resamples. It's cheap.
- **Download:** the first `selfcheck --asr` downloaded 2.47 GB of model files (about 5.5 minutes),
  kept in `.tools/`.

## 4. Microphone under launchd

Steps: [launchd_mic/README.md](launchd_mic/README.md). This feeds P-13.

| Check                                                    | Target              | Result | Pass |
| -------------------------------------------------------- | ------------------- | ------ | ---- |
| Prompt shown when started by launchd? Name it shows      | a prompt, clear name | A popup appeared within a second of the first launchd run and was allowed. It's named after the Python program, not "Earshot". | Partly: a prompt, but not a clear name |
| Verdict under launchd after granting                     | audio came through  | Audio came through: Python 3.11.18 started by launchd (parent pid 1), recording the AirPods at 24 kHz | Yes |
| Verdict from Terminal                                    | audio came through  | Audio came through | —    |
| After switching the interpreter: asked again? verdict    | note                | Audio came through with Python 3.12.16 under launchd. Each interpreter got its own grant: Privacy & Security → Microphone lists both Python versions. | —    |

Notes:

- **Started from Terminal:** each run was started with `launchctl kickstart` from Terminal. An
  agent that macOS starts at login might be treated differently, so test the real LaunchAgent at
  a real login in Phase 1.
- **Which program macOS checked:** the interpreter it would have checked lives inside the repo
  (`.tools/python/cpython-3.11.18-…/bin/python3.11`, then `cpython-3.12.16`), because of D-013.
- **What this means:** macOS ties the mic grant to the exact Python program. Every Python update
  (uv's managed Python changes even on patch releases) would bring a new popup named after Python,
  probably at login when nobody's watching. This is the case for P-13.

## 5. Head motion

Steps: [motion/README.md](motion/README.md).

| Check                                                      | Target                         | Result | Pass |
| ---------------------------------------------------------- | ------------------------------ | ------ | ---- |
| Motion available from a Mac CLI; prompt shown and its name | works                          | Only as its own app. Run from Terminal, macOS stopped the tool with `abort` as soon as it asked for motion. Built and opened as a signed app (`run.sh`), it got a Motion & Fitness prompt, was allowed, and worked. | Yes, as an app |
| Axes: nod and shake (`calibrate`)                          | note                           | Inconclusive. The motion stream was still connecting during the nod window, so it recorded nothing; shakes looked strongest on z. Calibration now waits for motion; a re-run is pending. | —    |
| Deliberate nods and shakes detected (`count --minutes 2`)  | all of them                    | Detected, but over-counted: 18 nods and 15 shakes in 2 minutes of deliberate gestures, often several per gesture and across axes (a nod also firing a shake) | Partly |
| Threshold used                                             | note                           | The plan's v1 detector: two opposite swings over 1.0 rad/s within 1.2 s | —    |
| False nods per hour of normal work, raw                    | note                           | 49 nods and 79 shakes in 61 minutes, none made on purpose (48 and 78 per hour) | —    |
| False nods per hour inside answer windows (estimate)       | ≤ 1                            | 0.80 at 10 tier-1 prompts an hour, 2.41 at 30. Per prompt, about 8% of 6-second answer windows would contain a nod you didn't make. | Only at 10 prompts an hour |
| Motion sample rate                                         | note                           | 50 Hz, steady for the hour, with one brief disconnect and reconnect | —    |

Notes:

- **It has to be an app.** Head motion only worked once the spike ran as its own signed app with a
  motion usage string, opened through Launch Services. That's more evidence for P-13's helper app.
- **False nods come in bursts:** for example, five within 2 s at 8:01:45, likely stretching,
  drinking or laughing. A trained classifier (the plan's gesture workstream) or stricter rules are
  needed before a nod approves anything. See P-18.
- **Next:** re-run `./run.sh calibrate` with the fix to confirm the axes. Labelled `log` sessions
  will seed the gesture dataset later.

## 6. Voiceprint

Steps: [voiceprint/README.md](voiceprint/README.md).

| Check                                                         | Target                 | Result | Pass |
| ------------------------------------------------------------- | ---------------------- | ------ | ---- |
| Your held-out phrases: lowest score                           | note                   |        | —    |
| Friend's phrases: highest score                               | note                   |        | —    |
| Gap (your lowest minus their highest)                         | > 0                    |        |      |
| ONNX vs PyTorch, lowest cosine across all lengths             | ≥ 0.999                |        |      |
| Exporter that worked (dynamo or legacy)                       | note                   |        | —    |
| onnxruntime-only process: ms per embedding and peak memory    | about 100 MB           |        |      |

Notes:

## Go/no-go

| Week-1 test                                 | Pass? | Notes |
| ------------------------------------------- | ----- | ----- |
| 1. Claude Code hook round trip              | Yes   | Q-1 answered: the dialog shows while the hook runs. Hook start 19.7 ms median. |
| 2. Speech in and out on the M2 with AirPods | Yes, with changes (P-17) | Parakeet v2 with a Whisper second listen gets yes/no 100% in quiet and noise, missing nothing, in 70 ms median. Still open: Kokoro's first audio (237 ms against 200), the 1.2 s second listens, and memory above 3 GB until the models are quantised. |
| 3. Head motion                              | Yes, with changes (P-18) | Motion works from a signed app at 50 Hz. The v1 detector gives 48 false nods an hour, so nods shouldn't approve until a stricter detector is proven. |
| 4. Voiceprint                               |       |       |

Decided at the gate, from the numbers above:

- **Q-1 and Q-2:** answered? Copy the answers into `decisions.md`.
- **P-05** (confidence threshold), **P-06** (answer-window guard) and **P-13** (where mic
  capture lives): accept, change or reject each.
- Anything here that changes the plan, such as nods (section 5) or barge-in (section 3).

**Decision:** Go / No-go, on (date), by (name). If it's Go, add a decision entry that the Step 0
gate passed; the next release is then `0.1.0`, the first of Phase 1 (D-006).
