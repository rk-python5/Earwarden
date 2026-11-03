# Step 0 results and go/no-go note

Fill this in as the spikes run. The Step 0 gate: all four week-1 tests pass, written up with
numbers. When it passes, record it in `decisions.md`; Phase 1 starts after that.

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
