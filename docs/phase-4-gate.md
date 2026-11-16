# Phase 4 gate: the session on the Mac

Phase 4's code is done: the floor manager, push-to-talk, the risk-gate interface, the audit
anchor and the red-team suite, which runs with every `pytest`. What's left needs rehaan, the
AirPods, friends for one step, and a working day for the soak. Each step says what it does, why,
what to watch for, and how long it takes. Claude analyses the results afterwards and records them
in `decisions.md`; the targets are in `docs/phase-4-plan.md` ("The gate").

Start every terminal in the repo with `source dev/activate`. Keep the hooks in `~/earshot-scratch`.
Claude can run every command here; rehaan's part is the AirPods, the voice and the day.

## 1. Set up (3 minutes)

```sh
git pull
uv sync --group voice
uv run pytest
helpers/earshot-motion/build.sh
```

- `pytest` now includes the red-team suite; everything should pass, about 1,050 tests in 40 s.
- The helper is rebuilt because its code changed since the last session (the stem, and its
  start-up). macOS will ask for the mic and motion once more, in Earshot's name (the ad-hoc
  signature, P-21).

## 2. Start the daemon for the session (2 minutes)

Terminal A:

```sh
uv run earshotd --home .tools/earshot --voice --pin-voice --keep-audio --stem \
  --helper helpers/earshot-motion/.build/EarshotMotion.app 2>&1 | tee .tools/earshot/soak.log
```

- `--stem` makes the helper the "Now Playing" app, so a press of the AirPods stem reaches
  Earshot. While it runs, the stem won't play or pause music (D-032).
- Allow the mic and motion when asked. Watch for "helper connected", both permissions granted,
  and "listening for the stem".
- `--keep-audio` keeps each answer's audio in `.tools/earshot/audio/`, for the false-approval
  check after the soak. Delete it when done.

## 3. Push-to-talk and the floor (10 minutes)

With the AirPods in, in terminal B:

| Run | Do | Expect |
| --- | --- | --- |
| 1 | press the AirPods stem once | the listening tone; say "status" → "No sessions are open." (or the sessions) |
| 2 | press, say "chatty mode" | "Chatty mode." |
| 3 | `uv run earshot status --home .tools/earshot` | the same briefing, printed |
| 4 | `uv run earshot talk --home .tools/earshot`, say "quiet mode" | "Quiet mode." |
| 5 | press, say "yes" | "Sorry, I didn't catch that." (a command window never approves) |
| 6 | `uv run earshot test --home .tools/earshot`, then press the stem during the question | nothing: a press never interrupts an answer window; answer "yes" → allow |
| 7 | press, say "repeat" | the last thing Earshot said |
| 8 | `uv run earshot test --tier 2 --home .tools/earshot`, don't answer; press, say "details" | the request, with its critical field spelled out; the request is still waiting (it goes to the screen after the window) |
| 9 | `uv run earshot mode focus --home .tools/earshot` | "Mode: focus." |

If the stem press does nothing (run 1), tell Claude: `earshot talk` is the fallback (D-032),
and the rest still runs.

## 4. The replay attack (5 minutes)

Terminal B, with the AirPods in and the Mac's own speaker on:

```sh
uv run python dev/redteam_replay.py --home .tools/earshot --runs 6
```

- It sends six tier-2 requests and, each time Earshot asks, plays one of your recorded
  "approve <word>" phrases through the Mac's speaker, as an attacker with a recording of you
  would. The fresh word never matches, so every run must end on the screen.
- It prints each run's result and what was heard. **Any "allow" fails the gate.**

## 5. Friends (3 minutes each; Q-5, deferred from Phase 2)

Stop terminal A's daemon (Ctrl-C). For each friend, wearing your AirPods, after asking them:

```sh
uv run earshot enroll --home .tools/earshot --record alex \
  --helper helpers/earshot-motion/.build/EarshotMotion.app
```

Then calibrate, and restart the daemon (step 2):

```sh
uv run python dev/calibrate_voiceprint.py --home .tools/earshot \
  --yours .tools/earshot/enroll --impostors .tools/earshot/calibration --write
```

- It prints the threshold that lets at most 2% of your friends' phrases through, and how often
  you'd be refused there, and saves it with `--write`.
- Then one live run: `uv run earshot test --tier 2 --home .tools/earshot`, and a friend says the
  phrase Earshot asks for. Expect "Didn't catch that clearly; it's on your screen."

## 6. The soak (a working day, passive)

With terminal A's daemon running (step 2), open three Claude Code sessions in scratch projects
(`~/earshot-scratch` and two copies of it), with `claude --permission-mode default`. In
terminal B:

```sh
uv run python dev/soak.py --hours 8 --home .tools/earshot --log .tools/earshot/soak.log
```

- Work as usual with the AirPods in, answering prompts by voice when you're away from the
  keyboard. Don't nod on purpose.
- Every minute it samples the daemon's and the helper's memory and CPU, and counts from the log:
  helper reconnects, tracebacks, nods seen inside answer windows (nods stay off, so none can
  approve), and every decision.
- At the end, or on Ctrl-C, it prints the summary: memory growth, idle CPU, crashes and nods
  against the targets. It also lists how many requests were allowed; Claude checks each one's
  kept clip against what you said (P-20).

## 7. Optional: start at login (10 minutes; Phase 1's milestone 8)

```sh
uv run earshot service install --home .tools/earshot --voice \
  --helper helpers/earshot-motion/.build/EarshotMotion.app
launchctl kill SIGKILL gui/$(id -u)/dev.earshot.daemon
```

- The first installs a LaunchAgent that starts the daemon at login and restarts it if it dies.
  The second kills it on purpose; `uv run earshot doctor --home .tools/earshot` should show it
  running again within about 10 seconds.
- Then log out and back in, run `doctor` again, and `uv run earshot service uninstall`.

## Afterwards

Tell Claude it's done. Claude reads `soak.log`, `soak.jsonl`, the kept audio, the replay and
calibration results, records the gate in `decisions.md`, and releases 0.3.0 if every target is
met.
