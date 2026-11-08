# Next steps: picking up in a local session

Written 8 Nov 2026, when work moved from cloud sessions to Claude Code in VS Code on rehaan's Mac.
Updated the same day, after the Phase 1 gate. Read this after CLAUDE.md, and update or delete
sections as they're done.

## Where things stand

- **Step 0** passed its gate (D-014), released as 0.0.2. **Phase 1** passed its gate (D-026),
  released as 0.1.0. `main` is at 0.2.0.dev0.
- **Phase 2's code is done** (8 Nov): all nine milestones in `docs/phase-2-plan.md`, built
  without stopping at rehaan's request.
  - the policy engine, resolvers, critical fields and the fidelity checker, and redaction
  - lookalike packages
  - challenge words and the voiceprint
  - the signed helper with nods and shakes
  - 8-bit models and faster first words
- **What's left needs rehaan:** one batched session, `docs/phase-2-gate.md`.
  - sign the helper; enroll; friends' phrases and calibration
  - the live checks and a longer stretch of voice use (P-20)
  - the hour-long nod count
  - confirming P-21, the choices made while building
- **Until the gate passes:** tier 2 stays on the screen (no voiceprint is enrolled yet), and
  `earshotd --voice` stays in the scratch project (P-20).
- **CI** runs as one macOS job, and builds the helper too. GitHub's Mac runners were unreliable in
  early November, so a local `uv run pytest` is the dependable check.

## Working in a local session

- Claude can run commands on the Mac itself, including the voice stack. rehaan still has to wear
  the AirPods and speak.
- Tags can be pushed from the Mac, so a release no longer needs the separate tag step.
- **Careful with hooks.**
  - `earshot init` with no `--settings` edits `~/.claude/settings.json`. That file also governs
    the Claude Code session doing the development, so while `earshotd --voice --pin-voice` runs,
    that session's own prompts would be asked by voice.
  - Keep the hooks in the scratch project, `~/earshot-scratch`, set up on 8 Nov.
  - If the hooks ever end up global, `uv run earshot uninstall` restores the backup.
- `earshotd` runs under `uv run`, which holds uv's cache lock. Stop the daemon before running
  `uv cache prune`.
- The disk is tight (about 7 GB free on 8 Nov). `.tools/huggingface/` holds only the three models
  the daemon uses, plus ECAPA for the voiceprint; Step 0's other candidates were deleted.
- Set the commit author first (D-012): `git config author.name "rehaan"` and
  `git config author.email "108854279+rk-python5@users.noreply.github.com"`.

## 1. Run the Phase 2 gate

Everything is in `docs/phase-2-gate.md`, with each command explained. Afterwards Claude:

- reads `.tools/earshot/phase2.log`, the kept audio, the calibration and the nod count
- runs `uv run python dev/false_approvals.py` and `--challenges` on the new recordings
- records the gate in `decisions.md` (the next free D number), with P-21's answers
- releases 0.2.0 if every target in the plan's gate table is met, then starts 0.3.0.dev0

Day to day, the voice runs as in section 1 of that file. The hooks live in
`~/earshot-scratch/.claude/settings.local.json`.

## 2. After Phase 2

Phase 3 (summarizer and EarshotBench) is optional, since v1.0 can ship with templates only (the
spec). Decide with rehaan whether to do it or go straight to Phase 4 (sessions, the risk gate,
the red-team suite and the 8-hour soak). Plan it the way `docs/phase-2-plan.md` was written.

## 3. Later, and loose ends

- **Phases left to v1.0:** 3 (summarizer and EarshotBench; optional, since v1.0 can ship with
  templates only), 4 (sessions, the risk gate, hardening: the red-team suite and an 8-hour soak)
  and 5 (launch).
- Remove `misaki[en]` from the voice install before any public release (D-022, D-023).
- Anchor the audit chain's head outside the file (P-10's second half, Phase 4).
- P-14, the self-hosted runner for recorded-audio tests, is deferred (D-023).
- Observe mode (D-021) is optional; its counts would help tune Phase 2's tiers.
- Phase 1's milestone 8: the LaunchAgent at a real login, and its restart after a kill. This is
  step 8 of the gate session, optional.
- A narration whose first clause is long and has no comma, such as "earshot scratch wants to
  write hello dot t x t", still takes about 1 s to its first word. Whisper's first second listen
  also loads it, in about 4.5 s.
- Open questions: Q-3 (is "Earshot" clear enough as a name), Q-4, Q-5 (which friends), Q-6.
