# Next steps: picking up in a local session

Written 8 Nov 2026, when work moved from cloud sessions to Claude Code in VS Code on rehaan's Mac.
Updated the same day, after the Phase 1 gate. Read this after CLAUDE.md, and update or delete
sections as they're done.

## Where things stand

- **Step 0** passed its gate (D-014) and was released as 0.0.2.
- **Phase 1** passed its gate on 8 Nov (D-026) and was released as 0.1.0: a real Claude Code
  session, approved by voice through the AirPods. `main` is at 0.2.0.dev0.
- **The gate found a safety hole (P-20):** Parakeet heard non-speech, or the tail of a cut-off
  reply, as "Yeah." or another approval. It's fixed on Step 0's recordings (D-027): Silero VAD
  checks every reply, and a reply that began before the window is never parsed. But the live
  check found one more false approval (section 2), so P-20 is still open. Until it's closed,
  run `earshotd --voice` only with the hooks in a scratch project. A second live check (D-028)
  found no false approvals, and added a listening tone.
- **Never run on hardware yet:**
  - the LaunchAgent (`service.py`) at a real login, and its restart after a crash
  - presence routing without `--pin-voice`
- **CI** runs as one macOS job, but GitHub's Mac runners were unreliable in early November. A local
  `uv run pytest` on the Mac is the dependable check.

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

## 1. Set up and run the voice (about 5 minutes)

```sh
source dev/activate
git pull
uv sync --group voice     # the Mac-only voice libraries; plain `uv sync` leaves them out
uv run pytest             # expect everything to pass on macOS
```

The hooks are already in `~/earshot-scratch/.claude/settings.local.json`. To try the voice:

1. **Terminal A, at the repo:**
   `uv run earshotd --home .tools/earshot --voice --pin-voice 2>&1 | tee .tools/earshot/gate.log`.
   The models load in about 5 s. Each listen logs its noise floor, threshold and loudest level.
2. **Terminal B:**
   `uv run earshot doctor --home .tools/earshot --settings ~/earshot-scratch/.claude/settings.local.json`.
   Then run `uv run earshot test --home .tools/earshot` and answer in the AirPods.
3. **In `~/earshot-scratch`:** `claude --permission-mode default`.

## 2. Close P-20 (a live false approval remains)

D-027 has the numbers from the recordings and the live check. Live, VAD dropped a short "no",
then let through a faint sound that Parakeet heard as "Yeah.". The audio wasn't kept, so the
next fix needs real failure clips first:

1. Run the daemon with `--keep-audio`. Each reply's clip goes to `.tools/earshot/audio/`, with a
   line per clip in `clips.jsonl`: the levels, VAD's verdict, and the transcript.
2. Run a scripted set of `earshot test` answers, mostly denials: "no", "nope", talking over the
   question, a cough before "no", and a few approvals.
3. Try the candidate guards on those clips and on Step 0's: Whisper agreement on approvals, a
   minimum length of speech, and loudness against the room. Pick the cheapest that approves
   nothing it shouldn't.
4. Delete `.tools/earshot/audio/` when done; it holds rehaan's voice.

Done on 8 Nov (D-028): the second live check found 0 false approvals in 10 runs, and the clips
showed what was breaking barge-in and timing. rehaan declined the loudness rule. What's left:

- The tone was tried live the same day, and answers given after it were heard. Talking while
  Earshot speaks, even an "okay", stops the question (barge-in): wait for the tone.
- Use voice in the scratch project for a longer stretch with `--keep-audio`, then look for any
  approval whose clip isn't a clear "yes". If none turns up, ask rehaan whether P-20 can close
  before the voiceprint arrives.

To repeat the live check, start the daemon as in section 1 and watch its log. Then run
`uv run earshot test --home .tools/earshot` three times:

1. **Say "yes".** It should allow.
2. **Cough or tap an AirPod during the answer window, then say "yes".** The log should show
   `not speech: ignored` for the noise, and it should still allow.
3. **Talk over the question ("no, don't do it").** Playback stops, the log shows `began before
   the window`, and Earshot says "Sorry, say yes or no". Say "no": it should deny.

If those hold, record the result in D-027 and drop the scratch-project-only rule from this file,
CLAUDE.md and the README. After any change to the listening path, run
`uv run python dev/false_approvals.py` (about 10 minutes); it must report 0 false approvals.

## 3. Build Phase 2, the safety layer

Planned on 8 Nov in `docs/phase-2-plan.md`. rehaan accepted P-01, P-02, P-08, P-09 and P-11 as
D-029. The plan has nine milestones, the gate's targets, and the decisions still open: Q-5
(which friends), and whether tier 1 also checks the voiceprint.

Milestones 1 to 3 (the policy engine, its resolvers, critical fields and the fidelity checker)
were done on 8 Nov. They replaced the safety stub, and tier 2 stays on the screen until challenge
words and the voiceprint are both in. Next is milestone 4: lookalike packages.

## 4. Later, and loose ends

- **Phases left to v1.0:** 3 (summarizer and EarshotBench; optional, since v1.0 can ship with
  templates only), 4 (sessions, the risk gate, hardening: the red-team suite and an 8-hour soak)
  and 5 (launch).
- Remove `misaki[en]` from the voice install before any public release (D-022, D-023).
- Anchor the audit chain's head outside the file (P-10's second half, Phase 4).
- P-14, the self-hosted runner for recorded-audio tests, is deferred (D-023).
- Observe mode (D-021) is optional; its counts would help tune Phase 2's tiers.
- Milestone 8: install the LaunchAgent (`uv run earshot service install --home … --voice`), then
  check it starts at a real login and restarts a killed daemon.
- Kokoro's first audio is 195 ms for a short sentence but 409 ms for a full narration sentence,
  against a 200 ms budget. Whisper's first second listen also loads it (about 4.5 s).
- Open questions: Q-3 (is "Earshot" clear enough as a name), Q-4, Q-5 (which friends), Q-6.
