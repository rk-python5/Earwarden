# Next steps: picking up in a local session

Written 8 Nov 2026, when work moved from cloud sessions to Claude Code in VS Code on rehaan's Mac.
Read this after CLAUDE.md. Update or delete sections as they're done.

## Where things stand

- **Step 0** passed its gate (D-014) and was released as 0.0.2.
- **Phase 1** code is complete on `main` (0.1.0.dev0): milestones 1–9 in `docs/phase-1-plan.md`.
  395 tests pass. What's left is the **gate**: a real Claude Code session approved by voice.
- **Never run on hardware yet:** `src/earshot/voice/mac.py` (Kokoro, the AirPods mic, Parakeet and
  Whisper), `voice/presence.py` (keyboard idle time) and `service.py` (the LaunchAgent). Everything
  else is tested with the real hook against the real daemon.
- **CI** runs as one macOS job, but GitHub's Mac runners were unreliable in early November. A local
  `uv run pytest` on the Mac is the dependable check.

## What changes in a local session

- Claude can run commands on the Mac itself, including the voice stack. rehaan still has to wear
  the AirPods and speak.
- Tags can be pushed from the Mac, so a release no longer needs the separate tag step.
- **Careful with hooks.** `earshot init` with no `--settings` edits `~/.claude/settings.json`, which
  also governs the Claude Code session doing the development. While `earshotd --voice --pin-voice`
  runs, that session's own prompts would be asked by voice. For development, install the hooks into
  a scratch project instead:
  `uv run earshot init --home .tools/earshot --settings ~/earshot-scratch/.claude/settings.local.json`.
  If the hooks are already global, `uv run earshot uninstall` restores the backup.
- Set the commit author first (D-012): `git config author.name "rehaan"` and
  `git config author.email "108854279+rk-python5@users.noreply.github.com"`.

## 1. Set up (about 5 minutes)

```sh
source dev/activate
git pull
uv sync --group voice     # the Mac-only voice libraries; plain `uv sync` leaves them out
uv run pytest             # expect everything to pass on macOS
```

## 2. Run the Phase 1 gate (about 20 minutes)

1. Make a scratch project (`mkdir -p ~/earshot-scratch && cd ~/earshot-scratch && git init`) and
   install the hooks there, as above.
2. In one terminal at the repo: `uv run earshotd --home .tools/earshot --voice --pin-voice`. The
   models load first; macOS asks for the microphone the first time it listens.
3. In another: `uv run earshot doctor --home .tools/earshot`, then
   `uv run earshot test --home .tools/earshot`, and answer "yes" in the AirPods.
4. In the scratch project: `claude --permission-mode default`. Ask it to create `hello.txt` and say
   "yes" by voice, without clicking the dialog. Then ask for a `git push` or `curl` and check it's
   only announced, with "it's on your screen".
5. `uv run earshot audit verify --home .tools/earshot` and `uv run earshot audit tail …`.

**Likely first fixes in `voice/mac.py`**, since none of it has run yet:

- mlx-audio internals: `_get_pipeline("a").g2p` and what calling the G2P returns (`can_say`).
- Picking the AirPods' input device and its 24 kHz rate; the resampling to 16 kHz.
- The energy endpointing thresholds (`_capture`) and the barge-in level (0.05), against real
  room noise. Step 0 measured playback leaking 16.7 dB below the noise floor.
- `sd.play` while an `InputStream` is open, and stopping playback on cancellation.
- Kokoro's first audio was 237 ms against a 200 ms budget; measure it in the daemon.
- `presence.idle_seconds()` parsing `ioreg` output on macOS 27.

Add tests for anything fixed that can be tested without hardware.

**When the gate passes:** add a decision (the next free D number) recording it, as D-014 did for
Step 0, with the evidence. Mark milestones 5, 8 and 9 done in `docs/phase-1-plan.md`. Then release
**0.1.0** by CLAUDE.md's release steps, and start `0.2.0.dev0`. Optionally,
`uv run earshot service install --home … --voice` starts the daemon at login.

## 3. Plan Phase 2, the safety layer (before writing its code)

Phase 2 is what makes voice safe for real work. Its gate: the safety targets in the spec's goals
table are met. Write `docs/phase-2-plan.md` the way `docs/phase-1-plan.md` was written, from the
spec's Phase 2 list plus what earlier decisions moved into it:

- the policy engine: YAML rules, tiers, the never-by-voice floor, `earshot policy check`. It
  replaces the safety stub (D-019) and must never be looser than it.
- resolvers (the real `git push` target, force flags, command splitting, obfuscation to tier 3,
  requirements files)
- critical-field extractors, the fidelity checker, and hardened secret redaction (entropy, a test
  corpus)
- lookalike checks against the top PyPI and npm names
- challenge words (about 200, from the week-1 recordings) and their matching
- the voiceprint: `earshot enroll`, ONNX, threshold calibration with 3–5 friends (Q-5)
- the signed Swift helper, `earshot-motion`: mic capture and device changes (moved here by
  D-023, from D-016) and head motion, with a fixed signing identity; the nod detector under D-018
- Silero VAD in place of energy endpointing (D-023)
- property tests for rules and resolvers

**Decisions due before Phase 2**, each with a recommendation in `decisions.md`: P-01 (tier 3 per
effect), P-02 (tier 0 and default tiers), P-08 (challenge-word matching, revised), P-09 (lookalike
thresholds), P-11 (repo policy only raises tiers). Ask rehaan for each, as the Phase 1 decisions
were asked.

## 4. Later, and loose ends

- **Phases left to v1.0:** 3 (summarizer and EarshotBench; optional, since v1.0 can ship with
  templates only), 4 (sessions, the risk gate, hardening: the red-team suite and an 8-hour soak)
  and 5 (launch).
- Remove `misaki[en]` from the voice install before any public release (D-022, D-023).
- Anchor the audit chain's head outside the file (P-10's second half, Phase 4).
- P-14, the self-hosted runner for recorded-audio tests, is deferred (D-023).
- Observe mode (D-021) is optional; its counts would help tune Phase 2's tiers.
- Open questions: Q-3 (is "Earshot" clear enough as a name), Q-4, Q-5 (which friends), Q-6.
