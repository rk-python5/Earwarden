# Phase 2 plan: the safety layer

Phase 2 makes voice safe for real work. Phase 1 answers prompts behind a safety stub (D-019) that
lets voice approve only edits inside the project and single test commands. Phase 2 replaces the
stub with the spec's policy engine and adds three things: summaries that can't drop a detail,
checks of who is answering, and the signed helper for the mic and head motion. This is the build
plan's "weeks 4–5", plus what Phase 1 and its gate moved here (D-023, D-026 to D-029).

**Gate:** the safety targets in the spec's goals table are met (see "The gate" below). When it
passes, record it in `decisions.md` and release 0.2.0 (D-006).

Keep this file current: mark a milestone done in the same commit that finishes it.

## Scope

From the build plan's Phase 2 list:

- the policy engine: YAML rules, tiers, the never-by-voice floor, and `earshot policy check`
- resolvers: the real `git push` target and force flags, command splitting, obfuscation to tier 3,
  and requirements files
- critical-field extractors, the fidelity checker and secret redaction
- the lookalike check against the top PyPI and npm lists
- challenge words: about 200, matched by sound
- the voiceprint: `earshot enroll`, ECAPA in ONNX, and threshold calibration
- the `earshot-motion` helper, and the v1 nod and shake detector inside answer windows only
- property tests for rules and resolvers

Moved here by decisions:

- the rules from P-01, P-02, P-08, P-09 and P-11 (D-029)
- the helper's mic capture and device changes (D-016, moved from Phase 1 by D-023)
- nods that never approve on their own (D-018)
- closing P-20: non-speech heard as an approval (D-027, D-028)
- carried costs: memory (the speech models exceed the 3 GB footprint), and Kokoro's first audio
  (409 ms for a long sentence, against 200 ms)

Not in Phase 2:

- the summarizer model and EarshotBench (Phase 3, optional)
- the floor manager's priorities, modes and briefings, the risk gate, the red-team suite and
  the 8-hour soak (Phase 4)
- packaging and launch (Phase 5)

## From the stub to the policy engine

The policy engine replaces the safety stub, and it must never be looser than the stub while the
pieces arrive:

- **Tier 3 goes to the screen**, as the stub's refusals do now.
- **Tier 2 goes to the screen until challenge words and the voiceprint are both in** (milestones
  5 and 6). Only then does a tier-2 request get "To install, say: approve orchard."
- **Tier 1 is voice-approvable**, as the stub allows now. A test replays every request the stub
  sends to the screen and checks the engine doesn't make it tier 1.

## Milestones

In build order. "Code" means Claude builds and tests it, on the Mac or in a cloud session. "Mac"
means it needs rehaan, the AirPods, other people's voices or Xcode.

| # | Milestone                                    | Where     | Rests on            | Status |
| - | -------------------------------------------- | --------- | ------------------- | ------ |
| 1 | The policy engine and `earshot policy check` | Code      | D-029 (P-02, P-11)  | Done   |
| 2 | Resolvers and per-effect rules               | Code      | D-029 (P-01)        | Done   |
| 3 | Critical fields, the checker, redaction      | Code      | D-024               | Done   |
| 4 | Lookalike packages                           | Code      | D-029 (P-09)        | Done   |
| 5 | Challenge words                              | Code, Mac | D-029 (P-08)        | Code   |
| 6 | The voiceprint                               | Code, Mac | D-014, Q-5          | Code   |
| 7 | The helper: mic, devices and head motion     | Mac       | D-016, D-018, D-023 | Code   |
| 8 | Close P-20, memory and latency               | Code, Mac | D-027, D-028        | Code   |
| 9 | The gate                                     | Mac       | —                   | Ready  |

### 1. The policy engine and `earshot policy check` (code)

- Tiers from four sources, and the most restrictive wins:
  - built-in defaults per tool (P-02): tier 0 means tier 1; reads outside the project are at
    least tier 2; unknown tools, and Bash commands no rule matches, are tier 2
  - your `~/.earshot/policy.yaml` (under `--home`, `<home>/policy.yaml`)
  - a repo's `.earshot/policy.yaml`, which can only raise tiers. Lowering one needs
    `earshot policy trust`, which pins the file's hash; a changed file is untrusted again (P-11).
  - the never-by-voice floor: push to the default branch, force push, secrets, recursive
    delete, deploy, pipe to shell, and changes to the agent's permissions are tier 3, and no
    file or model can lower them
- The secret paths cover `.env`, `id_rsa`, `id_ed25519`, `id_ecdsa`, `*.pem`, `*.key`,
  credentials, `.netrc`, `.npmrc`, `.pypirc`, `~/.kube/config` and `~/.docker/config.json` (P-02).
- `earshot policy check request.json` prints the tier, the rules that fired and the critical
  fields, without speaking.
- The daemon and the audit log use the engine's tier and rules in place of the stub's.
- **Done when:**
  - tests cover each default, each source and the floor
  - a repo policy that tries to lower a tier is refused until trusted, and untrusted again after
    a change
  - no request the stub sends to the screen comes out tier 1
- **Done (8 Nov):**
  - `earshot/policy/` (`engine.py` and `file.py`), with `earshot policy check` and
    `earshot policy trust`. The daemon, the audit log and observe mode use it in place of the
    stub. PyYAML is a new dependency.
  - The floor's shell effects (force push, a push naming the default branch, recursive delete,
    piping into a shell, deploys, the agent's files) are found by pattern until milestone 2.
  - One deliberate difference from the stub: reads inside the project are tier 1 (the spec's
    tier 0, by P-02), where the stub sent every read to the screen.

### 2. Resolvers and per-effect rules (code)

- **`git push`:**
  - It reads the real target: `git rev-parse --abbrev-ref HEAD` and `@{u}` in the session's
    folder, read-only. A bare `git push` on `main` is tier 3.
  - Force is parsed properly: `-f`, `--force`, `--force-with-lease` and `+refspec`.
  - Refspecs are understood: `HEAD:main`, `src:dst`, `:dst` (a delete), plus `--mirror`, `--all`,
    `--delete` and `git -C` (P-01).
- **Git aliases are expanded** before judging, and `git config` and `git -c` are tier 3 (P-01).
- **Commands are split** on `&&`, `||`, `;`, pipes and subshells. Each part is judged, and the
  highest tier wins.
- **Anything that can't be checked statically is tier 3:** `eval`, `bash -c "$(...)"`,
  `base64 -d | sh` and `curl ... | sh`.
- **`pip install -r` reads the requirements file** and lists what it would install.
- **Per effect (P-01):**
  - Edits to `.git/`, `.claude/`, `.earshot/`, `.github/workflows/` and `.envrc` are tier 3.
  - Edits to build and test config (`conftest.py`, `package.json`, `Makefile`, `pyproject.toml`,
    `setup.py`) are at least tier 2.
  - Running code after such an edit in the same session is at least tier 2. The daemon keeps
    each session's recent actions for this (`recent_actions` in the spec).
- **Done when:**
  - property tests (hypothesis) show a tier never drops below its rule, whatever the flags,
    quoting, chaining or whitespace
  - the two-step attacks from P-01 come out tier 2 or 3: `conftest.py` then `pytest`, and an
    alias then its use
- **Done (8 Nov):**
  - `policy/shell.py`: a small shell parser. It splits commands, reads quotes, follows `$(...)`,
    backticks and heredocs, and reports what can't be read statically.
  - `policy/bash.py`: judges each simple command. It sees through wrappers, parses `sh -c`, and
    finds pipes into a shell, recursive deletes, deploys, and writes to protected or outside
    places. It follows `cd`.
  - `policy/git.py`: aliases, `-C`, and where a push goes, read from the repository.
  - `policy/places.py`: the path checks, shared with the edit tools.
  - The hook now sends an edit's file path with PostToolUse. A session where build or test config
    was edited raises every later Bash command to at least tier 2.
  - Property tests (hypothesis) disguise floor commands with quoting, spacing, wrappers,
    subshells, `bash -c` and chaining. None drops below tier 3.
  - The engine reads quotes, so a plain test run with a quoted argument is tier 1, where the stub
    refused any quote.

### 3. Critical fields, the checker and redaction (code)

- **Extractors** pull the critical fields for each action, from the spec's table:
  - push: remote, effective branch, force
  - install: every package, version pins, a non-default index
  - write or edit: file and parent folder, and whether it's outside the project
  - delete: targets, recursive
  - network call: domain, a method other than GET, whether data is sent
  - MCP tool: server, tool, main argument
- **The fidelity checker:**
  - Every critical field must appear in the spoken sentence, in its spoken form.
  - Any identifier in the sentence that isn't in the request fails it.
  - A sentence over about 25 words isn't approvable by voice.
- **Redaction** adds entropy detection to the patterns. A test corpus of real-looking keys and
  near-misses checks it never speaks or logs a secret.
- **Done when:** every template passes the checker on a corpus of real requests, and the redaction
  corpus has no misses.
- **Done (8 Nov):**
  - `policy/fields.py` extracts each action's critical fields from the engine's reading, so a
    bare `git push` names the branch it really pushes. `pip install -r` lists the file's
    packages.
  - The narrator says one clause per command ("run the tests, then push feature to origin").
  - `narrator/checker.py` refuses a sentence that drops a field or uses a word the request and
    the narrator's own vocabulary don't give it. A refused sentence sends the request to the
    screen.
  - Redaction knows GitLab, Stripe, Google, SendGrid, npm, PyPI, Hugging Face and Twilio tokens.
    It also catches secrets named by assignments (`AWS_SECRET_ACCESS_KEY=`) and options
    (`--password`), and leaves `max_tokens=1000` alone.
  - A policy rule's `critical:` and `resolve:` must name known fields and resolvers.

### 4. Lookalike packages (code)

- Vendor snapshots of the top 15,000 PyPI packages and npm's most-depended-upon list. They're
  refreshed at release time, never fetched at runtime, and their licences are checked.
- **The rule (P-09):**
  - exact matches and the whole list are exempt
  - the edit distance scales with name length: no flag up to 5 letters, 1 for 6–8, 2 for 9 or
    more
  - confusable characters are always checked
- A flagged name is spelled out, said ("this looks like requests"), and made tier 3.
- **Done when:**
  - recall is measured on the ecosyste.ms typosquat dataset and recorded with the thresholds
  - false flags on the legitimate 5,001–15,000 range stay near the measured 3.9%
- **Done (8 Nov):**
  - `policy/lookalike.py`, with the lists in `policy/data/`:
    - PyPI's top 15,000 names, from hugovk's dump of 1 Nov. The source has no licence, so only
      the names are kept. rehaan to confirm this is acceptable.
    - npm-high-impact's 17,338 names (MIT).
    - `dev/refresh_package_lists.py` rebuilds both at release time.
  - npm names keep their separators: there, `uglify.js` and `uglify-js` differ.
  - False flags: 4.0% of names ranked 5,001–15,000, if they weren't exempt (P-09 measured 3.9%).
  - Recall on the ecosyste.ms dataset (CC0, kept as a test fixture), for squats of popular
    names over 5 letters: PyPI 57 of 64, npm 17 of 25.
    - The misses are combosquats (`requests-darwin-lite`), and names 2 edits from an 8-letter
      target.
    - Under P-09's thresholds, squats of 5 letters or fewer (`numoy`) pass unless confusable.
  - A lookalike is tier 3, spelled out, and said as "which looks like requests".

### 5. Challenge words (code, then Mac)

- **The words (P-08):**
  - Pick about 200 that are easy to say, at least 2 Double Metaphone edits apart from each other,
    and as far from common English words.
  - Step 0's ten words are the seed.
- **The prompt:** "To install, say: approve orchard.", with a fresh random word each time.
- **The match (P-08):**
  - The challenge word must end a reply of four words or fewer, with no negation.
  - The carrier word is ignored.
  - D-015's guards apply, since the prompt ends with the answer.
- **On the Mac:** rehaan records a sample of the words in quiet and noisy rooms. They go into the
  recorded-audio set, which grows towards the spec's 200 replies.
- **Done when:** on the recordings, every genuine reply is accepted at the spec's yes/no rates, and
  no decoy or wrong word is.
- **Code done (8 Nov):**
  - `voice/challenge.py` and 200 words in `voice/data/challenge-words.txt`. They're built by
    `dev/build_challenge_words.py` from about 630 easy nouns, keeping only words Kokoro's
    front-end can say. `metaphone` (BSD) is a new dependency.
  - Every pair of words is at least 2 Double Metaphone edits apart, and so is every word from
    the "everyday words" set. That set is the reply words plus about 150 common words, a
    narrower reading of P-08's "common English words".
  - The decider asks "To install, say: approve harbor." Tier 2 stays on the screen until a
    voiceprint is enrolled (milestone 6).
  - On Step 0's recordings (`dev/false_approvals.py --challenges`), with the old ten words:
    - 27 of 30 genuine replies matched. The 3 misses were noisy-room recognition errors, and
      they're asked again.
    - 7 of 8 decoys, wrong words and bare yeses were refused. The one false match is P-08's own
      case: noise turned "approve orchid" into "a plum orchard". `orchard` isn't in the new
      list, and a match still needs the voiceprint.
  - **Left for the Mac:** rehaan records a sample of the new words, quiet and noisy.

### 6. The voiceprint (code, then Mac)

- **`earshot enroll`** records 12 phrases (about 45 s) through the AirPods mic, in headset mode.
  It builds an ECAPA profile with Step 0's ONNX export and onnxruntime, so no PyTorch is needed.
- **Calibration:**
  - rehaan's held-out recordings, over several days and rooms
  - impostors: 3–5 friends (Q-5) through the same AirPods, plus public clips used only for score
    distributions
  - output: a DET curve, the threshold at no more than 2% impostors, and rehaan's false-reject
    rate there
- **Tier 2 needs both** the challenge word and the voiceprint. A borderline score gets "Didn't
  catch that clearly; it's on your screen."
- **Decide with rehaan:** whether tier-1 approvals also check the voiceprint. That would close
  P-20's faint "Yeah.", but a one-word "yes" may be too short to verify. Measure it first.
- **Done when:** impostors are accepted at most 2% of the time, and rehaan's voice at least 95%
  of the time on the first try.
- **Code done (8 Nov):**
  - `voice/voiceprint.py`: ECAPA's filterbank in numpy, ECAPA on onnxruntime (MIT, in the
    voice group), the profile (0600, a template, no audio) and the verdicts.
    - The threshold starts at 0.50, from Step 0's mid-point, with 0.45–0.50 borderline.
    - `dev/export_ecapa.py` exports the model (83.8 MB) into the home's `models/`.
    - Parity: features within 0.0012 dB of SpeechBrain's, and embeddings at cosine 1.000000
      with PyTorch's on every Step 0 recording.
  - `earshot enroll`: 12 phrases plus 6 held out, spoken as challenge phrases in headset mode.
    `--record NAME` records a friend's phrases, or more of yours, for calibration.
  - `dev/calibrate_voiceprint.py` gives the equal error rate and the threshold at no more than
    2% impostors, and `--write` saves it.
    - On Step 0's recordings (one friend), rehaan's lowest was 0.535 and the friend's highest
      0.438, a gap of +0.097.
    - It trims with Silero, as the live path effectively does, and an energy trim had kept
      the Enter key's click.
  - The daemon scores every answer once a profile exists. Tier 2 needs a match, and tier 1's
    scores go to the audit log, as data for P-20's question.
  - **Left for the Mac:** rehaan enrolls. 3–5 friends record impostor phrases (Q-5), then
    calibrate.

### 7. The helper: mic, devices and head motion (Mac)

- **`helpers/earshot-motion/`,** a Swift app signed with a fixed identity (D-016). It:
  - captures the AirPods mic, converts it to 16 kHz mono, and streams it to the daemon
  - reports device changes, such as the AirPods connecting or the output switching
  - streams head motion (rotation rates) from `CMHeadphoneMotionManager`
- The daemon reads audio from the helper in place of sounddevice. The mic permission belongs to
  the helper, so it survives Python updates.
- **The nod detector (D-018):**
  - It counts only in tier-1 answer windows.
  - A nod never approves on its own: either nods stay off, or a stricter double nod is required.
  - A shake hands the request to the screen.
- **Mac setup:** full Xcode and a free Apple Development certificate.
- **Done when:**
  - macOS asks for the mic once, in the helper's name
  - the grant survives a rebuild
  - the hour-long count shows under 1% of answer windows with a false nod
- **Code done (8 Nov):**
  - `helpers/earshot-motion/`, a Swift app (`EarshotMotion.app`, `dev.earshot.motion`, no Dock
    icon), built and signed by `build.sh`. It's signed with `$EARSHOT_SIGNING_IDENTITY`, or ad
    hoc, and CI builds it.
  - It captures the headset mic at 16 kHz while asked, streams Core Motion rotation rates while
    asked, and reports device changes and permissions.
  - `voice/helper.py` is the daemon's end: a private Unix socket and the shared token, in JSON
    lines. `earshotd --voice` always serves it, and `--helper PATH` launches the app through
    Launch Services. The Mac voice uses it whenever it's connected, and sounddevice otherwise.
  - `voice/gestures.py`:
    - A shake in the answer window hands off.
    - Nods are off unless `earshotd --nods`. Then a strict double nod approves tier 1 only:
      two nods within 2 s, pitch at least twice yaw and roll, a second of stillness first.
    - The audit records the gesture.
  - `dev/count_false_nods.py` runs the hour-long count.
  - **Left for the Mac (rehaan):** check macOS asks for the mic once, in Earshot's name; and the
    hour-long count.
  - **Deferred (rehaan, 9 Nov): the fixed signature.** The helper is signed ad hoc for now, so
    macOS asks again after each rebuild, and the "grant survives a rebuild" check stays open.
    - The fix for this Mac: a self-signed code-signing certificate from Keychain Access, used by
      `EARSHOT_SIGNING_IDENTITY=… build.sh`. No Xcode is needed.
    - For other users: an Apple Developer ID and notarisation, in Phase 5.

### 8. Close P-20, memory and latency (code, then Mac)

- **P-20:**
  - Use voice in the scratch project for a longer stretch with `--keep-audio`.
  - Run `dev/false_approvals.py` after every change to listening.
  - With the voiceprint (milestone 6), ask rehaan whether P-20 can close.
- **Memory:** the footprint target is at most 3 GB resident.
  - Try 8-bit Parakeet and 4-bit Whisper, keeping Whisper loaded only when needed.
  - Re-run the recorded-audio checks after each change.
  - Removing `misaki[en]` (D-022) drops PyTorch from the voice install.
- **Latency:** Kokoro's first audio should be at most 200 ms. Split long sentences into shorter
  chunks for the first audio.
- **Code done (8–9 Nov):**
  - **Memory:** Parakeet and Whisper are quantised to 8 bits at load, and MLX's cache is cleared.
    - The footprint falls from 3.16 GB to 1.68 GB, and with Whisper loaded from 4.85 GB to
      2.85 GB, under the 3 GB target.
    - Parakeet at 8 bits: 108 of 110 intents right, as at 32 bits, and 109 of 110 word for
      word.
    - Whisper at 8 bits: 108 of 110 right, as at 16 bits. 4 bits was worse (107, 74 word for
      word) and slower.
    - The recorded-audio check with these models: 0 false approvals, all 18 approvals heard, and
      109 of 110 replies heard as labelled.
  - **Latency:** Kokoro speaks clause by clause (commas, colons and semicolons too), and makes
    each clause while the chime or the last clause plays.
    - Its first audio fell from a median of 588 ms to 227 ms.
    - The first word after the speech starts fell from 1,116 ms to 562 ms; about 0.64 s from
      the prompt, inside the spec's 0.7 s.
    - A long first clause without a comma still takes about 1 s.
    - An MLX lock keeps two models from running at once.
  - **P-20:** left to the gate session's longer stretch of voice use (`docs/phase-2-gate.md`).
  - Removing `misaki[en]` (D-022) stays a Phase 5 task, before any public release.

### 9. The gate (Mac)

The spec's goals table, and how each target is measured:

| Target                          | Measured by                                                  |
| ------------------------------- | ------------------------------------------------------------ |
| Tier 3 by voice: never          | rule and property tests, and P-01's two-step attacks         |
| Yes/no ≥ 98% quiet, ≥ 95% noisy | the recorded-audio set, with every live guard on             |
| Impostors at tier 2 ≤ 2%        | the voiceprint calibration                                   |
| rehaan at tier 2 ≥ 95%, 1st try | held-out enrollment recordings                               |
| Summary fidelity 100%           | the checker on a corpus of real requests                     |
| False nods ≤ 1 an hour          | the hour-long count, inside answer windows                   |
| No false approvals              | `dev/false_approvals.py`, and a live run with `--keep-audio` |
| 0 prompts lost when down        | the kill-the-daemon test                                     |

Footprint and latency are measured and recorded, but they don't gate Phase 2, unless rehaan
decides they should. The session that runs the gate is `docs/phase-2-gate.md`.

## Decisions Phase 2 needs

| Needed before | Item                                               | Status                   |
| ------------- | -------------------------------------------------- | ------------------------ |
| Milestone 1   | P-02 tier 0 and default tiers                      | Accepted as D-029        |
| Milestone 1   | P-11 repo policy only raises tiers                 | Accepted as D-029        |
| Milestone 2   | P-01 tier 3 per effect                             | Accepted as D-029        |
| Milestone 4   | P-09 lookalike thresholds                          | Accepted as D-029        |
| Milestone 5   | P-08 challenge-word matching (revised)             | Accepted as D-029        |
| Milestone 6   | Q-5 which friends record impostor phrases          | Open                     |
| Milestone 6   | Whether tier 1 also checks the voiceprint (P-20)   | Open: measure, then ask  |
| Milestone 7   | P-13 the signed helper; P-18 nods                  | Accepted as D-016, D-018 |
| Milestone 8   | P-20 non-speech heard as an approval               | Open (D-027, D-028)      |

## Where things live during development

As in Phase 1:

- Libraries, models and tools stay inside the repo (D-013).
- Earshot's data, now including `policy.yaml`, goes under `.tools/earshot/`.
- Hooks go into `~/earshot-scratch`, never the global settings.
- The PyPI and npm snapshots and the challenge-word list are versioned in the repo, since nothing
  is fetched at runtime.

## Testing

- **CI, on every push:**
  - unit and property tests for the policy engine, resolvers, extractors, the checker,
    redaction, lookalikes and challenge-word matching
  - `hypothesis` joins the dev tools
- **rehaan's Mac, at each Mac milestone:**
  - `dev/false_approvals.py`, and the recorded-audio set as it grows (by hand, since P-14 is
    deferred)
  - a live `earshot test` round with `--keep-audio`
