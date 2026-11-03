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
| Date                             |       |
| Mac (chip, memory)               |       |
| macOS version                    |       |
| Claude Code version              |       |
| AirPods model and firmware       |       |
| Earshot version / commit         |       |

## 1. Hook probe

Steps: [hook_probe/README.md](hook_probe/README.md).

| Check                                                    | Target                 | Result | Pass |
| -------------------------------------------------------- | ---------------------- | ------ | ---- |
| `allow` honoured, no dialog                              | yes                    |        |      |
| `deny` honoured, the message reaches Claude              | yes                    |        |      |
| No output brings up the normal dialog                    | yes                    |        |      |
| **Q-1:** dialog shown while the hook holds? (run 4)      | answer                 |        | —    |
| Late hook decision vs. an on-screen answer (run 5)       | answer                 |        | —    |
| How Esc ends a waiting hook (run 6)                      | answer                 |        | —    |
| `permission_prompt` notification during a hold (run 7)   | answer                 |        | —    |
| Hook process start, median and p95 (`bench`)             | well under 80 ms       |        |      |
| `PreToolUse` → `PermissionRequest` gap, median (`report`) | note                  |        | —    |
| Decision → `PostToolUse` gap, median (`report`)          | note                   |        | —    |
| Payload has the fields the plan's ApprovalRequest needs  | yes                    |        |      |

Notes:

## 2. Speech

Steps: [speech/README.md](speech/README.md).

| Check                                                        | Target                   | Result | Pass |
| ------------------------------------------------------------ | ------------------------ | ------ | ---- |
| Kokoro time to first audio, median and p95                   | ≤ 200 ms                 |        |      |
| Kokoro real-time factor                                      | note                     |        | —    |
| Kokoro peak memory                                           | about 0.2 GB             |        |      |
| Parakeet yes/no correct, quiet                               | ≥ 98%                    |        |      |
| Parakeet yes/no correct, noisy                               | ≥ 95%                    |        |      |
| Transcript exact, quiet and noisy                            | note                     |        | —    |
| False approvals, all 100 replies                             | 0                        |        |      |
| Recognition time per reply, median                           | inside the 260 ms stage  |        |      |
| Parakeet peak memory                                         | about 1.3 GB             |        |      |
| Confidence threshold: % of wrong caught, % of right re-asked | pick a threshold         |        | —    |
| Plan's Double Metaphone matcher on the decoys                | rejects them             |        |      |
| Words skipped without espeak-ng (`g2p_coverage.py`)          | none, after normalising  | 476 of the top 1,000 PyPI names (47.6%) and 48 of 87 identifiers have no phonemes; all come back when spelled letter by letter (measured 3 Nov 2026) | No: needs P-03 |

Notes:

## 3. AirPods audio I/O

Steps: [audio_io/README.md](audio_io/README.md).

| Check                                                          | Target                         | Result | Pass |
| -------------------------------------------------------------- | ------------------------------ | ------ | ---- |
| **Q-2:** mic live after opening, median and max (`switch`)     | note; decides keeping it warm  |        | —    |
| Output glitches when the mic opens                             | note                           |        | —    |
| Output-to-mic delay (`leak`)                                   | note; sets the window guard    |        | —    |
| Leak gain and leak above the noise floor (`leak`)              | note; decides barge-in         |        | —    |
| Self-approval, any guard, with and without pre-roll (`selfcheck`) | never approves              |        |      |
| Smallest guard where every window is quiet (`selfcheck`)       | pick it                        |        | —    |

Notes:

## 4. Microphone under launchd

Steps: [launchd_mic/README.md](launchd_mic/README.md). This feeds P-13.

| Check                                                    | Target              | Result | Pass |
| -------------------------------------------------------- | ------------------- | ------ | ---- |
| Prompt shown when started by launchd? Name it shows      | a prompt, clear name |       |      |
| Verdict under launchd after granting                     | audio came through  |        |      |
| Verdict from Terminal                                    | audio came through  |        | —    |
| After switching the interpreter: asked again? verdict    | note                |        | —    |

Notes:

## 5. Head motion

Steps: [motion/README.md](motion/README.md).

| Check                                                      | Target                         | Result | Pass |
| ---------------------------------------------------------- | ------------------------------ | ------ | ---- |
| Motion available from a Mac CLI; prompt shown and its name | works                          |        |      |
| Axes: nod and shake (`calibrate`)                          | note                           |        | —    |
| Deliberate nods and shakes detected (`count --minutes 2`)  | all of them                    |        |      |
| Threshold used                                             | note                           |        | —    |
| False nods per hour of normal work, raw                    | note                           |        | —    |
| False nods per hour inside answer windows (estimate)       | ≤ 1                            |        |      |
| Motion sample rate                                         | note                           |        | —    |

Notes:

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
| 1. Claude Code hook round trip              |       |       |
| 2. Speech in and out on the M2 with AirPods |       |       |
| 3. Head motion                              |       |       |
| 4. Voiceprint                               |       |       |

Decided at the gate, from the numbers above:

- **Q-1 and Q-2:** answered? Copy the answers into `decisions.md`.
- **P-05** (confidence threshold), **P-06** (answer-window guard) and **P-13** (where mic
  capture lives): accept, change or reject each.
- Anything here that changes the plan, such as nods (section 5) or barge-in (section 3).

**Decision:** Go / No-go, on (date), by (name). If it's Go, add a decision entry that the Step 0
gate passed; the next release is then `0.1.0`, the first of Phase 1 (D-006).
