# Phase 2 gate: the session on the Mac

Phase 2's code is done. What's left needs rehaan, the AirPods, and for one step, friends. This is
everything in one place, in the order that wastes least time. Each step says what it does, why,
what to watch for, and how long it takes. Claude analyses the results afterwards and records them
in `decisions.md`; the targets are in `docs/phase-2-plan.md` ("The gate").

Start every terminal in the repo with `source dev/activate`. Keep the hooks in `~/earwarden-scratch`.

## 1. Set up (5 minutes)

```sh
git pull
uv sync --group voice
uv run pytest
```

- `uv sync --group voice` installs everything Phase 2 added: onnxruntime for the voiceprint, and
  metaphone for challenge words. It takes about a minute.
- `uv run pytest` should pass everything, about 800 tests in 30 seconds.

The voiceprint model is already exported to `.tools/earwarden/models/` (8 Nov). If it's ever
missing, `uv run dev/export_ecapa.py --home .tools/earwarden` makes it again, in about 5 minutes,
and checks it against SpeechBrain.

## 2. Build the helper (2 minutes)

```sh
src/earwarden/helper_app/build.sh
```

- It compiles the Swift helper and wraps it as `EarwardenMotion.app`, signed ad hoc. It takes about
  a minute the first time.
- **A fixed signature is deferred** (rehaan, 9 Nov). An ad-hoc signature changes with every build,
  so macOS asks for the mic and motion again after each rebuild of the helper. That's harmless,
  just a prompt. To fix it later, make a self-signed "Code Signing" certificate in Keychain
  Access (Certificate Assistant > Create a Certificate, named `Earwarden Dev`), then build with
  `EARWARDEN_SIGNING_IDENTITY="Earwarden Dev" src/earwarden/helper_app/build.sh`. Other users' Macs
  need an Apple Developer ID (Phase 5).

## 3. Start the daemon with the helper (5 minutes)

Terminal A:

```sh
uv run earwardend --home .tools/earwarden --voice --pin-voice --keep-audio \
  --helper src/earwarden/helper_app/.build/EarwardenMotion.app 2>&1 | tee .tools/earwarden/phase2.log
```

- This starts Earwarden with the helper. The helper now captures the mic and reads head motion.
- `--keep-audio` keeps each answer's audio in `.tools/earwarden/audio/`, so Claude can check what
  was heard. Delete that folder when we're done.
- macOS asks twice, **in Earwarden's name**: for the microphone, and for motion. Allow both.
- Watch the log for "helper connected" and "helper permissions: {'mic': 'granted', 'motion':
  'granted'}".

There's no rebuild check this time: with an ad-hoc signature, macOS asks again after a rebuild,
as expected. It's deferred with the fixed signature (step 2).

## 4. Enroll your voice (3 minutes)

Stop the daemon (Ctrl-C), then:

```sh
uv run earwarden enroll --home .tools/earwarden --save-clips .tools/earwarden/enroll \
  --helper src/earwarden/helper_app/.build/EarwardenMotion.app
```

- `--helper` records through the helper, the channel Earwarden later checks your voice on. Stop
  the daemon first: both use the helper's socket.
- It asks for 18 phrases, such as "Say: approve harbor", each after a tone. Say each one
  naturally, as you'd answer Earwarden.
- 12 build your voiceprint, and 6 more check it. It prints your lowest and middle scores against
  the threshold (0.50 until calibration).
- It saves your voiceprint (a template, not audio) to `.tools/earwarden/voiceprint.json`, readable
  only by you. `--save-clips` also keeps the phrases, for calibration.

**More of your voice** (a minute each, on other days and in other rooms, if you can):

```sh
uv run earwarden enroll --home .tools/earwarden --record kitchen --save-clips .tools/earwarden/enroll \
  --helper src/earwarden/helper_app/.build/EarwardenMotion.app
```

## 5. Your friends' phrases (3 minutes each, Q-5)

3–5 friends, each wearing your AirPods:

```sh
uv run earwarden enroll --home .tools/earwarden --record alex \
  --helper src/earwarden/helper_app/.build/EarwardenMotion.app
```

- It records 12 phrases from them, for calibration only, into `.tools/earwarden/calibration/alex/`.
  No profile is made, and the recordings stay on your Mac. Ask them first.

Then calibrate (1 minute):

```sh
uv run python dev/calibrate_voiceprint.py --home .tools/earwarden \
  --yours .tools/earwarden/enroll --impostors .tools/earwarden/calibration --write
```

- It scores everyone's phrases against your voiceprint, and prints the threshold that lets at
  most 2% of your friends' phrases through, with how often you'd be refused. It leaves out the
  phrases that built your voiceprint, since they'd flatter it.
- `--write` saves that threshold into your voiceprint.

## 6. Live checks (10 minutes)

Restart terminal A's daemon (step 3). Then in terminal B, run `uv run earwarden test --home
.tools/earwarden` with these answers:

| Run | Command | What to do | Expect |
|---|---|---|---|
| 1 | `earwarden test` | after the tone, "yes" | allow |
| 2 | `earwarden test` | after the tone, shake your head | screen, "Okay, it's on your screen" |
| 3 | `earwarden test --tier 2` | after the tone, "approve" and the word it says | allow |
| 4 | `earwarden test --tier 2` | after the tone, "yes" | "Sorry, say: approve …"; then say it, allow |
| 5 | `earwarden test --tier 2` | have a friend say "approve" and the word | screen, "Didn't catch that clearly" |

Then work in `~/earwarden-scratch` with `claude --permission-mode default` for a while, answering by
voice: this is the longer stretch P-20 needs. Claude reads the kept audio afterwards.

## 7. The hour-long nod count (60 minutes, passive)

Stop the daemon. Then:

```sh
uv run python dev/count_false_nods.py --minutes 60 --home .tools/earwarden
```

- It opens the helper and records head motion for an hour while you work as usual, AirPods in.
  Don't nod on purpose. It never opens the mic.
- It reports how many 6-second windows held a false nod. The target is under 1%. It also
  reports the old v1 detector's count, for comparison (Step 0: 49 an hour).

## 8. Optional: start at login (10 minutes; Phase 1's milestone 8)

```sh
uv run earwarden service install --home .tools/earwarden --voice
launchctl kill SIGKILL gui/$(id -u)/dev.earwarden.daemon
```

- The first line installs a LaunchAgent, so the daemon starts at login and restarts if it dies.
  It keeps the models in `.tools/` (it passes `HF_HOME` on).
- The second kills the daemon on purpose. `uv run earwarden doctor --home .tools/earwarden` should
  show "earwardend is running" again within about 10 seconds.
- Then log out and back in, and run `doctor` again. `uv run earwarden service uninstall` removes
  the agent.

## Afterwards

Tell Claude it's done. Claude reads the logs, kept audio, calibration and count, records the gate
in `decisions.md`, and releases 0.2.0 if every target is met.
