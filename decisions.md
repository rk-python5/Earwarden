# Decisions

The running decision log for Earshot. The design doc,
[docs/design/earshot-technical-design-build-plan.pdf](docs/design/earshot-technical-design-build-plan.pdf)
(revision of 3 Nov 2026), is the baseline. Anything that changes, clarifies or adds to it is
recorded here, never by editing the PDF.

How this file works:

- **Decisions** (`D-NNN`) are numbered in the order they're made. Entries are never deleted; a
  reversed decision is marked *Superseded by D-NNN*.
- **Proposals** (`P-NN`) need rehaan's call. An accepted proposal becomes a new decision that
  cites it; a rejected one is marked *Rejected* with the reason.
- **Open questions** (`Q-N`) track the plan's unknowns and where each gets answered.
- An entry is added or changed in the same commit as the change it describes.

## Index

| ID    | Decision                                                  | Status   |
| ----- | --------------------------------------------------------- | -------- |
| D-001 | The design doc is the baseline spec                       | Accepted |
| D-002 | Design decisions settled in the doc                       | Accepted |
| D-003 | Work on `main` only                                       | Accepted |
| D-004 | Commits in logical groupings                              | Accepted |
| D-005 | Commit authorship                                         | Superseded by D-012 |
| D-006 | Versioning                                                | Accepted |
| D-007 | Living project docs: CLAUDE.md, decisions.md, CHANGELOG.md | Accepted |
| D-008 | Distribution name `earshot-agents`, import name `earshot` | Accepted |
| D-009 | Tooling: uv, Python 3.11, ruff, mypy, pytest              | Accepted |
| D-010 | CI on GitHub-hosted macOS 15, Apple Silicon               | Accepted |
| D-011 | Step 0 also measures the design-review risks              | Accepted |
| D-012 | Every commit is authored by rehaan                        | Accepted |
| D-013 | On the Mac, every install stays inside the repo           | Accepted |
| D-014 | The Step 0 gate passed                                    | Accepted |
| D-015 | The answer window can't hear Earshot's own prompt (P-06)  | Accepted |
| D-016 | A signed Swift helper owns the macOS plumbing (P-13)      | Accepted |
| D-017 | Two-stage recognition: Parakeet, then Whisper (P-17)      | Accepted |
| D-018 | Nods don't approve on their own (P-18)                    | Accepted |

## Decisions

### D-001 The design doc is the baseline spec

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** rehaan
- **Decision:** "Earshot — Technical Design & Build Plan", revision of 3 Nov 2026, stored at
  `docs/design/earshot-technical-design-build-plan.pdf`, is the spec the build follows.
- **Consequences:** Deviations live in this file. A new revision of the doc replaces the PDF at the
  same path (git keeps the old ones) and gets its own entry here.

### D-002 Design decisions settled in the doc

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** design doc (decision log)

| Decision             | Choice                                            | Revisit when                          |
| -------------------- | ------------------------------------------------- | ------------------------------------- |
| Daemon language      | Python                                            | Start-up time or memory is a problem  |
| Hook transport       | Command hook + Unix socket, not an HTTP hook      | HTTP hooks gain authentication        |
| Who decides          | Rules decide; models only phrase                  | Never, for tier decisions             |
| Summaries            | Templates first, model second, checker always     | —                                     |
| Silence              | Hand to the screen, never auto-deny               | —                                     |
| Tier 3               | Never by voice                                    | Two-person rule in v2.0               |
| Speaker model runtime | ONNX, not PyTorch                                | An MLX port appears                   |
| Where it runs        | Fully local                                       | —                                     |

### D-003 Work on `main` only

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** rehaan
- **Decision:** All work is committed directly to `main` and pushed. No feature branches, no pull
  requests.
- **Consequences:** Every push runs CI on `main`, so run the checks locally before pushing and keep
  `main` green.

### D-004 Commits in logical groupings

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** rehaan
- **Decision:** Each commit holds one coherent change (a spike, a component, a fix). Unrelated
  changes never share a commit. `decisions.md`, `CHANGELOG.md`, `README.md` and `CLAUDE.md` are
  updated in the same commit as the change they describe, and lock files travel with the change
  that needs them.

### D-005 Commit authorship

- **Date:** 2026-11-03 · **Status:** Superseded by D-012 · **By:** rehaan
- **Decision:** Material rehaan provides (design docs, recorded results, notes) is committed with
  author `rehaan <108854279+rk-python5@users.noreply.github.com>`, the GitHub noreply address of
  `rk-python5`, so it counts on rehaan's GitHub profile. Work Claude writes is committed under the
  session's own identity and ends with the `Co-Authored-By` and `Claude-Session` trailers.

### D-006 Versioning

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** rehaan (asked for versioning); scheme by
  Claude
- **Decision:**
  - Semantic Versioning, `MAJOR.MINOR.PATCH`, written in PEP 440 form so Python tooling accepts it.
    Work between releases carries a `.devN` suffix, for example `0.0.1.dev0`.
  - One source of truth: `version` in `pyproject.toml`, changed with `uv version`. Code reads it
    with `importlib.metadata`.
  - Before 1.0 the minor number tracks the build plan: `0.0.x` Step 0 (feasibility), `0.1.x`
    Phase 1 (walking skeleton), `0.2.x` Phase 2 (safety layer), `0.3.x` Phase 3 (summarizer and
    EarshotBench v0), `0.4.x` Phase 4 (sessions, risk gate, hardening), `1.0.0` Phase 5 (public
    launch). A phase's first release, `0.N.0`, can only be cut once the previous phase's gate is
    recorded as passed here.
  - A release is one commit that moves the changelog's *Unreleased* section under the new version
    and sets the version, plus an annotated tag `vX.Y.Z` on that commit, pushed to GitHub. Tags are
    signed from `v1.0.0`, as the plan's launch section asks.
  - Wire formats are versioned on their own: the `v` field in IPC messages and `version:` in policy
    files are integers that change only on breaking changes.

### D-007 Living project docs: CLAUDE.md, decisions.md, CHANGELOG.md

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** rehaan
- **Decision:** Three files are kept current with every change:
  - `CLAUDE.md`: working rules, commands, layout and invariants for Claude Code sessions. It's
    upper-case (the request said "claude.md") because that's the name Claude Code loads
    automatically.
  - `decisions.md`: this log.
  - `CHANGELOG.md`: notable changes, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
    format.

### D-008 Distribution name `earshot-agents`, import name `earshot`

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** design doc (launch section's fallback
  order: `earshot`, then `earshot-ai`, then `earshot-agents`)
- **Context:** `earshot` and `earshot-ai` are taken on PyPI (Q-3); `earshot-agents` is free.
- **Decision:** The PyPI distribution is `earshot-agents`. The import package (`from earshot import
  Earshot`) and the commands (`earshot`, `earshotd`, `earshot-hook`) keep the name `earshot`.
- **Consequences:**
  - pykeio's voice-activity-detection library on PyPI also uses the import name `earshot`, so the
    two can't share one environment. `uv tool install` isolates Earshot, but a user's own agent
    environment could hit the clash. Revisit if rehaan renames the project (the rest of Q-3).
  - The name isn't reserved until the first upload. That's rehaan's call, and soon is safer:
    `earshot-ai` was registered the day before the plan was dated.

### D-009 Tooling: uv, Python 3.11, ruff, mypy, pytest

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** design doc (tech stack), details by Claude
- **Decision:**
  - **uv** manages the environment, the lock file (`uv.lock`, committed) and the build, through the
    `uv_build` backend.
  - **Python:** `.python-version` pins 3.11 and `requires-python` is `>=3.11`.
  - **Layout:** `src/` package layout.
  - **Lint and format:** ruff, line length 100, with a security rule set (`S`) because this is a
    safety tool.
  - **Types:** mypy in strict mode.
  - **Tests:** pytest, with warnings treated as errors.
  - **Spikes** declare their own dependencies inline (PEP 723) and run with `uv run`. Heavy,
    macOS-only libraries (MLX, PyTorch, sounddevice) stay out of the project lock.
- **Consequences:** If packaging later needs build hooks that `uv_build` lacks (for example
  bundling the Swift helper), switch to hatchling and record it here.

### D-010 CI on GitHub-hosted macOS 15, Apple Silicon

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** design doc (macOS CI job), details by Claude
- **Decision:**
  - `.github/workflows/ci.yml` runs on every push to `main` (and on demand): `uv sync --locked`,
    then ruff (lint and format), mypy and pytest.
  - A second job builds the Swift head-motion spike (`swift build` in `spikes/motion`), so Swift
    written in the Linux dev container is compiled before rehaan runs it.
  - It runs on `macos-15`. GitHub retired the `macos-14` image on 2026-11-02, so macOS 14, the
    plan's minimum, can only be tested on a real Mac.
  - Third-party actions are pinned to a commit SHA; GitHub's own actions to a major version.
- **Consequences:** Hosted runners have no Metal (see P-14), so jobs that need MLX models will need
  a self-hosted runner.

### D-011 Step 0 also measures the design-review risks

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** Claude, within Step 0 (measurement only; no
  design change; rehaan can veto)
- **Decision:** The week-1 spikes also collect evidence for the review proposals, so each can be
  decided on numbers. This adds no new spikes: it extends the four the plan already has, plus one
  short permission check.
  - **speech:** pronunciation coverage without espeak-ng (P-03, P-04), per-word ASR confidence
    (P-05), and decoy and negation replies in the recorded set (P-07, P-08).
  - **audio_io:** a self-approval check: answer windows cut after the prompt, with and without
    pre-roll, transcribed (P-06).
  - **launchd_mic:** one short permission check: whether a launchd-started Python process gets
    the microphone, and whether the grant survives a change of interpreter (P-13).
  - **voiceprint:** an ONNX parity check across phrase lengths, plus the memory of an
    onnxruntime-only process. These back the settled choice to run the speaker model in ONNX
    (D-002).
- **Consequences:** Results for these go in the same sections of `spikes/RESULTS.md`. They don't
  change the Step 0 gate, which stays as the plan defines it.

### D-012 Every commit is authored by rehaan

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** rehaan (supersedes D-005)
- **Decision:** Every commit, including the ones Claude writes, has the author
  `rehaan <108854279+rk-python5@users.noreply.github.com>`, so the work shows on the `rk-python5`
  profile. In cloud sessions:
  - The committer stays the session identity, which signs commits. A signature only shows as
    verified on GitHub when the signing key belongs to the committer.
  - Claude's part is credited by the `Co-Authored-By` trailer.
  - Sessions set the author with repo-local git config (`author.name`, `author.email`). A fresh
    clone doesn't carry that config, so `CLAUDE.md` asks each session to set it first.

### D-013 On the Mac, every install stays inside the repo

- **Date:** 2026-11-04 · **Status:** Accepted · **By:** rehaan
- **Decision:** Everything Earshot installs on rehaan's Mac goes through venvs inside the repo
  folder. `source dev/activate`, once per terminal:
  - creates `.tools/uv-venv`, a venv that holds uv itself, installed with pip from the Mac's
    `python3`, and puts only `uv` and `uvx` on that terminal's PATH
  - points uv's cache, Python downloads and tool folders at `.tools/`, and Hugging Face downloads
    at `.tools/huggingface/`

  The Python 3.11 that uv downloads, the dev tools, and every spike's libraries and models all end
  up in `.tools/` or `.venv/`, both git-ignored. Nothing goes into the home folder or the shell
  profile, and deleting the two folders removes it all.
- **Exceptions:** Xcode, which the Swift spike needs, and the Mac's own `python3`, used once to
  make the uv venv.
- **Consequences:** D-009 stands: uv is still the tool, and this decides where it lives on the Mac.
  CI and cloud sessions keep their preinstalled uv. The docs no longer suggest the system-wide uv
  installer or `brew install uv`.
- **Tested:** in a fresh clone with no uv on PATH and an empty home folder, `source dev/activate`,
  `uv sync`, the full test suite and a spike script all ran. `.venv` was built on the Python in
  `.tools/python`, the spike's environment landed in `.tools/cache`, and nothing was written to the
  home folder.

### D-014 The Step 0 gate passed

- **Date:** 2026-11-04 · **Status:** Accepted · **By:** rehaan
- **Decision:** Step 0 passes its gate. All four week-1 tests pass and are written up with numbers
  in `spikes/RESULTS.md`, so Phase 1, the walking skeleton, can start.
  - **Hook round trip:** yes. The hook starts in 19.7 ms (median), and Claude Code shows its own
    dialog while the hook runs (Q-1).
  - **Speech in and out:** yes, with two-stage recognition (D-017). Yes/no was 100% right on the
    100 recorded replies, quiet and noisy.
  - **Head motion:** yes, with nods not approving on their own (D-018). Motion works from a signed
    app at 50 Hz.
  - **Voiceprint:** yes. A friend's voice was told apart from rehaan's by +0.112 with the silence
    trimmed, and ECAPA in ONNX matches PyTorch at every length.
- **Settled at the gate:**
  - P-05 is rejected.
  - P-06, P-13, P-17 and P-18 are accepted as D-015 to D-018.
  - Barge-in works as the plan hoped: playback leaks into the mic 16.7 dB below the room's noise
    floor, so the half-duplex fallback isn't needed with these AirPods.
- **Carried into Phase 1:**
  - Kokoro's first audio took 237 ms, against a 200 ms budget.
  - Whisper's second listens add about 1.2 s.
  - Memory: the speech models exceed the 3 GB footprint until they're quantised, and the speaker
    model's onnxruntime process peaked at 206 MB.
- **Consequences:** Release 0.0.2 closes Step 0, and Phase 1's releases are `0.1.x` (D-006).

### D-015 The answer window can't hear Earshot's own prompt

- **Date:** 2026-11-04 · **Status:** Accepted · **By:** rehaan, at the Step 0 gate (accepts P-06)
- **Decision:**
  - The answer window opens only after playback has really ended, plus the measured output delay.
  - Pre-roll never reaches back before the window opened.
  - "Earshot hears itself" joins the red-team suite.
- **Why:** The tier-2 prompt ends with the exact answer ("say: approve orchard"), and at tier 1
  nothing else stands in the way. Step 0 found no leak with rehaan's AirPods 4, but the guards are
  cheap, and other headsets may leak more.

### D-016 A signed Swift helper owns the macOS plumbing

- **Date:** 2026-11-04 · **Status:** Accepted · **By:** rehaan, at the Step 0 gate (accepts P-13)
- **Decision:** `earshot-motion` is a small signed background app, a real app bundle. It owns mic
  capture, device changes, the push-to-talk hotkey and head motion, and streams 16 kHz audio to
  `earshotd`. Python keeps the models and the logic.
- **Why (Step 0):**
  - macOS grants the mic to a launchd-started Python separately for each interpreter, so every
    Python update would bring a new prompt, named after Python rather than Earshot.
  - Head motion only worked from a signed app bundle with a usage string, opened through Launch
    Services. Run from Terminal, macOS stopped it with `abort`.
  - Rebuilding an ad hoc–signed app reset its permission, so the helper needs a signing identity
    that stays the same across builds. An Apple Development certificate does that on rehaan's Mac;
    public releases need Developer ID and notarisation.
- **Consequences:** The plan builds `earshot-motion` in Phase 2, for head motion only. Its mic
  capture and device changes move into Phase 1, because speech in and the LaunchAgent depend on
  them. Head motion stays in Phase 2, and the hotkey comes with push-to-talk.

### D-017 Two-stage recognition: Parakeet first, Whisper when unclear

- **Date:** 2026-11-04 · **Status:** Accepted · **By:** rehaan, at the Step 0 gate (accepts P-17)
- **Decision:**
  - Parakeet v2 hears every reply, after voice-activity trimming.
  - Only when its answer is unclear, an empty transcript included, does Whisper large-v3-turbo
    get a second listen on the same audio.
  - Both answers go through the same intent rules (P-07, P-08 and P-16 decide those).
- **Why:** On rehaan's 100 recordings, no single recogniser met the plan's yes/no targets (98%
  quiet, 95% noisy) within its 260 ms budget. Together they got 100% in quiet and noise and missed
  no approvals. The second listen ran on 23 of 100 replies; time per reply was 70 ms median and
  1.2 s p95.
- **Consequences:**
  - This replaces the plan's confidence score (P-05, rejected). A reply that's still unclear after
    the second listen gets asked once more, then goes to the screen.
  - Phase 1 handles the costs: the 1.2 s second listens (try shorter Whisper windows or a smaller
    Whisper), and memory (try 8-bit Parakeet and 4-bit Whisper, or load Whisper only when needed).

### D-018 Nods don't approve on their own

- **Date:** 2026-11-04 · **Status:** Accepted · **By:** rehaan, at the Step 0 gate (accepts P-18)
- **Decision:**
  - In v1.0 a nod never approves on its own. Either nods ship off (`nods = false`), or they need a
    stricter pattern: a double nod within 2 s, with pitch clearly dominating yaw and roll, after
    about a second of stillness. That pattern must be re-measured with the hour-long count and
    stay under 1% of answer windows.
  - A shake never denies on its own; it hands the prompt to the screen.
  - Labelled `log` sessions build the plan's gesture dataset and classifier.
- **Why:** On rehaan's AirPods 4, the plan's v1 detector counted 48 false nods in an hour of normal
  work, so about 8% of answer windows would hold a nod nobody made. Calibration showed that shakes
  move the nod axis at two-thirds of a nod's speed.
- **Consequences:** Phase 2's nod detector is the stricter pattern; until it's proven, tier 1 relies
  on voice.

## Proposals

From the design review of 3 Nov 2026. Each needs rehaan's call by the point listed.

### P-01 Hold the tier-3 promise per effect, not just per request

- **Problem:** Tiers are judged one request at a time, so ordinary approvals can add up to a tier-3
  action. Editing `conftest.py` (tier 1) and then running `pytest` (tier 1 in the example policy)
  can force-push to `main` on two nods. So can `git config alias.sync "push -f origin main"`
  followed by `git sync`, since neither matches `^git push\b`.
- **Proposal:**
  - Make edits to `.git/`, `.claude/`, `.earshot/`, `.github/workflows/` and `.envrc` tier 3.
  - Make edits to build and test config (`conftest.py`, `package.json`, `Makefile`,
    `pyproject.toml`, `setup.py`) at least tier 2.
  - Raise the tier for running code after such an edit in the same session (what `recent_actions`
    is for).
  - Expand git aliases, and treat `git config` and `git -c` as tier 3.
  - Teach the push resolver `HEAD:main`, `src:dst`, `:dst` (delete), `--mirror`, `--all`,
    `--delete` and `git -C`.
  - Add two-step attacks to the red-team suite, and word the public claim exactly.
- **Decide by:** before Phase 2.

### P-02 Define tier 0 and fix the default tiers

- **Problem:** Tier 0 has no path in the life-of-an-approval flow. If it means "allow without
  asking", Earshot grants what the user's own Claude Code settings didn't. Earshot only ever sees
  requests that prompt, and reads inside the project don't prompt. So "read tools are tier 0" rates
  the risky out-of-project reads lowest. `Read ~/.ssh/id_ed25519` also slips past the example
  secrets rule, which only knows `id_rsa`. The plan gives no default tier for Bash commands that
  match no rule.
- **Proposal:**
  - Tier 0 means "same as tier 1"; nothing is allowed without an answer.
  - Out-of-project reads are at least tier 2.
  - Secret paths also cover `id_ed25519`, `id_ecdsa`, `.netrc`, `.npmrc`, `.pypirc`,
    `~/.kube/config`, `~/.docker/config.json` and `*.key`.
  - Unmatched Bash commands default to tier 2.
- **Decide by:** before Phase 2.

### P-03 Check that the summary can be spoken, not only that the text is right

- **Problem:** In mlx-audio 0.6.4, when espeak-ng isn't installed, the Kokoro pipeline logs
  "OOD words will be skipped" and drops words its dictionary doesn't know. Branch names, package
  names and lookalikes such as `reqeusts` are exactly those words. The fidelity checker reads the
  text, so it passes a sentence whose key words are silent.
- **Evidence (Step 0, 3 Nov 2026, `spikes/speech/g2p_coverage.py`):** With no fallback, misaki
  0.9.4 gives no phonemes for:
  - 476 of the top 1,000 PyPI package names (47.6%)
  - 48 of 87 typical identifiers
  - "quickstart" in one of the plan-style summaries

  Spelled letter by letter, all of them come back.

  On the Mac (4 Nov), turning the fallback off made sentence 01 half a second shorter, because
  "quickstart" was dropped.
- **Proposal:** The checker runs the pronunciation step and rejects any sentence with a word that
  gets no phonemes, and the normaliser spells such words letter by letter. Step 0 measures this
  (`spikes/speech`).
- **Decide by:** before the Phase 1 narrator.

### P-04 Own the Kokoro text front-end to stay clear of GPL code

- **Problem:** mlx-audio's English Kokoro pipeline always imports `misaki.espeak`, which imports
  `phonemizer` (GPLv3+), even when espeak-ng isn't installed. The latest `misaki[en]` (0.9.4) also
  installs `espeakng-loader`, which bundles espeak-ng itself. Either breaks the plan's "never bundle
  espeak-ng". `misaki.en` also downloads the spaCy model at first use, which is a network call at
  runtime.
- **Also seen on the Mac (4 Nov):** `misaki[en]` pulled PyTorch into the voice's environment (a
  warning from `torch` at start-up). The leaner front-end avoids that, which matters for the 3 GB
  memory target.
- **Proposal:**
  - Call `misaki.en.G2P` directly and feed its phonemes to the Kokoro model; never import
    `misaki.espeak`.
  - Depend on `misaki` without the `[en]` extra, plus `spacy` and `num2words`.
  - `earshot init` installs the spaCy model ahead of time.
- **Decide by:** before Phase 1.

### P-05 Per-word recognition confidence

- **Problem:** The plan turns Parakeet's token probabilities into a confidence score that drives
  "ask once more". In mlx-audio 0.6.4 the decoder is greedy `argmax`, and its tokens carry text and
  timings but no probabilities.
- **Proposal:** Keep the softmax probability of each chosen token in a patched decode step. Step 0
  measures whether it separates right from wrong transcripts (`spikes/speech`).
- **Evidence (first Mac run, 4 Nov):** The patched decode works and matches mlx-audio's text on
  all 100 replies, but the score separates poorly. The median lowest-word probability is 0.597
  when right and 0.375 when wrong, and a 0.70 threshold catches 94% of errors while re-asking 65%
  of correct answers. On its own it's too weak a gate. A diagnosis run is pending.
- **Recommendation (4 Nov, after the recogniser comparison):** reject. The two-stage recogniser
  (P-17) uses "unclear" as its trigger and reaches the targets without a confidence score.
- **Status:** *Rejected* at the Step 0 gate (4 Nov 2026, rehaan). The two-stage recogniser (D-017)
  meets the targets with "unclear" as its trigger, and on its own the score told right
  transcripts from wrong ones too weakly.

### P-06 Earshot must not hear itself approve

- **Problem:** The tier-2 prompt ends with the exact answer ("say: approve orchard"). Bluetooth
  keeps playing after the Mac finishes sending audio, and the 1.5 s pre-roll can contain the tail of
  Earshot's own voice. Any leak into the mic can be transcribed as the answer. At tier 1 nothing
  else stands in the way.
- **Proposal:**
  - Open the answer window only after playback has really ended, plus the measured output delay.
  - Never take pre-roll from before the window opened.
  - Add "Earshot hears itself" to the red-team suite. Step 0 measures it (`spikes/audio_io`).
- **Evidence (Step 0, 4 Nov 2026, `audio_io`):** With the mic kept warm, none of 16 answer
  windows held any of the prompt's speech, at guards from 0 to 500 ms, with and without pre-roll.
  Playback leaks into the AirPods mic at 16.7 dB below the room's noise floor. With these AirPods
  the risk didn't show up; the cheap guards are still worth keeping, because other headsets may
  leak more.
- **Status:** Accepted at the Step 0 gate as D-015.

### P-07 Approve only on an exact whole-utterance match

- **Problem:** "Do it" is an approval phrase, and it's contained in "don't do it" and "do it
  later". Recognisers also drop short words like "don't".
- **Proposal:** Approval needs the whole utterance to match a short list exactly. Any negation or
  extra word means no approval: deny, instruction or ask again.
- **Evidence (Step 0, 4 Nov 2026):** Over 200 recognitions of rehaan's 100 recorded replies, the
  strict rules never approved anything that wasn't an approval, including "don't do it", "do it
  later" and "don't approve that". The cost is re-asks: about one reply in ten missed in quiet,
  after trimming.
- **Decide by:** before the Phase 1 intent rules.

### P-08 Challenge-word matching

- **Problem:** Double Metaphone codes "orchard" as ARXRT/ARKRT and "orchid" as ARKT, one edit
  apart; "orchards" and "archer" are also one edit away. Any edit-distance allowance on the codes
  lets "orchid" through, so the plan's own example fails. The codes are coarse for two-syllable
  words too. In a 20-word candidate list, five pairs were one code edit apart: meadow/summit,
  falcon/violin, velvet/walnut, walnut/violin, thistle/saddle. The Step 0 recordings use ten words
  that are pairwise at least two edits apart, plus decoys.
- **Evidence (first Mac run, 4 Nov):** No decoy passed. But in noise, "approve orchid" came out as
  "Uproom orchard": the recogniser turned the decoy into the real challenge word. The carrier
  word was often heard as "Approved" or "A proof", which rejected genuine answers. Both point the
  same way: match the carrier leniently, and pick challenge words that are far apart in sound,
  not just in spelling.
- **Evidence (diagnosis run, silence trimmed):**
  - "Approve" came out right in only 1 of 20 genuine challenge replies; the challenge word in 18.
  - The plan's Double Metaphone matcher accepted a correctly heard "Approve orchid." as "orchard".
- **Revised proposal:**
  - Let the challenge word decide: it must end a reply of four words or fewer that contains no
    negation. Ignore the carrier word; it's only there to give the voiceprint enough speech.
  - Pick the ~200 words so no two sound alike, because in noise the recogniser turned "orchid"
    into "orchard". In the recogniser comparison, every model did this at least once. Parakeet v3
    even produced the exact phrase "Approve orchard.", so close pairs are unsafe under any rule.
  - `asr_eval.py` reports this rule as a what-if.
- **Proposal:** Require an exact code match, or pick the ~200 words so every pair, and every word
  against common English words, is at least 2 code edits apart.
- **Decide by:** before Phase 2.

### P-09 Lookalike rule thresholds

- **Problem:** Measured against the top-PyPI list (15,000 packages, snapshot of 1 Nov 2026):
  - 23.5% of the top 5,000 are within edit distance 2 of another top-5,000 package (`boto3`/`boto`,
    `click`/`black`, `numpy`/`sympy`).
  - With exact matches exempt, 16.4% of the legitimate packages ranked 5,001–15,000 would still
    become tier 3, and 86% of those with names of five letters or fewer.
- **Proposal:**
  - Exempt exact matches and everything on the 15,000 list.
  - Scale the distance with name length: no edit-distance flag up to 5 letters (the
    confusable-character check still applies), 1 for 6–8 letters, 2 for 9 or more. That cuts the
    rate to 3.9%.
  - Measure recall on the ecosyste-ms squat dataset before settling.
- **Decide by:** before Phase 2.

### P-10 A keyed, anchored audit chain

- **Problem:** Anything that can write the audit file can recompute a plain SHA-256 chain, and that
  includes the agent's Bash, which runs as the user. Cutting off the newest records also leaves a
  valid chain.
- **Proposal:**
  - Key the chain with an HMAC key held in the Keychain.
  - Anchor the head hash outside the file from time to time.
  - Make touching Earshot's own files tier 3: the audit directory, config, token, policies and
    `~/.claude/settings.json`.
- **Decide by:** before the Phase 1 audit log.

### P-11 Repo policy can only raise tiers

- **Problem:** A cloned repo ships its own `.earshot/policy.yaml` and could lower tiers. Claude Code
  holds back a repo's hooks until the folder is trusted; Earshot has nothing similar.
- **Proposal:** Rules from a repo policy can only raise tiers. Lowering one needs an explicit trust
  step that pins the file's hash.
- **Decide by:** before Phase 2.

### P-12 Lifecycle while the hook waits

- **Problem (revised 4 Nov 2026 after Q-1):** Step 0 showed that Claude Code's dialog is on
  screen the whole time the hook runs, and whichever answers first wins. So the session never
  freezes. Instead, Earshot can go on speaking and listening about a request you've already
  answered at the keyboard:
  - Approving on screen lets the tool run, but the hook keeps waiting, and nothing tells it.
  - No or Esc end the hook with SIGTERM.

  Also, the plan's hook list has no `PostToolUse`, although its briefings rely on `PostToolUse`
  events.
- **Proposal:**
  - Install a `PostToolUse` hook too. When the requested tool runs, the daemon cancels the voice
    prompt and the waiting hook exits silently. `PermissionRequest` has no `tool_use_id`, so match
    on session, tool name and input.
  - A closed hook socket (SIGTERM after No or Esc) cancels the approval.
  - Since the dialog is always there, a waiting voice prompt costs nothing: while you're away, hold
    for close to the hook timeout and re-announce, instead of handing off at 90 s.
  - Register unknown sessions lazily from any request.
  - The audit log records that in sessions that can't show a prompt, "no output" means deny.
  - Expect the `permission_prompt` notification 6 s in, even while Earshot is asking by voice. Any
    desktop-notification hook you have will fire too.
- **Decide by:** before Phase 1.

### P-13 A signed Swift helper owns the macOS plumbing

- **Problem:**
  - Microphone permission for a launchd-started Python process is tied to the interpreter's code
    signature, which can change with every uv or Python upgrade.
  - The push-to-talk hotkey has no owner, and a global hotkey needs an event loop or Input
    Monitoring permission.
  - PortAudio lists devices only when it starts, so it won't notice AirPods connecting later.
- **Proposal:** Make `earshot-motion` a small signed background app that owns mic capture, device
  changes, the hotkey and head motion, and streams 16 kHz audio to `earshotd`. Python keeps the
  models and the logic. Step 0 tests launchd mic access (`spikes/launchd_mic`).
- **Evidence so far (Step 0, 4 Nov 2026, `launchd_mic`):**
  - Python started by launchd recorded real audio from the AirPods, with Python 3.11.18 and again
    after switching to Python 3.12.16.
  - macOS asked within a second, with a popup named after the Python program. It keeps a separate
    grant per interpreter: Privacy & Security → Microphone lists both Python versions. So the first
    problem is real. Every Python update means a new popup, named after Python rather than Earshot,
    most likely at login. A signed helper app would be asked once, under its own name.
  - Caveat: the runs were started from Terminal, and a login-started agent may differ.
  - Head motion (Step 0, 4 Nov): run from Terminal, the motion spike was stopped by macOS with
    `abort` as soon as it asked for motion. It worked only as its own signed app, with a motion
    usage string, opened through Launch Services, which then got its own Motion & Fitness prompt.
    So the helper must be a real app bundle, not a bare command-line tool.
  - Rebuilding the motion spike reset its permission to "not determined": its ad hoc signature
    changes with its code, so macOS treats each build as a new app. The helper needs a signing
    identity that stays the same across updates (an Apple Development or Developer ID
    certificate), or every update asks again.
- **Status:** Accepted at the Step 0 gate as D-016.

### P-14 Audio integration tests on a self-hosted runner

- **Problem:** GitHub-hosted Apple Silicon runners don't expose Metal, so the plan's integration
  layer (recorded replies through MLX models) probably can't run there.
- **Proposal:** Run that layer on rehaan's M2 as a self-hosted runner. Hosted macOS runners keep
  the unit, property and end-to-end layers.
- **Decide by:** before the Phase 1 integration tests.

### P-15 Auto mode means fewer, riskier prompts

- **Problem:** rehaan's Claude Code sessions start in auto mode. In Step 0's first hook-probe round,
  auto mode approved all seven `touch` commands by itself. No `PermissionRequest` reached the hook
  (21 payloads, all `permission_mode: auto`). Earshot only hears what Claude Code would have asked
  you. Under auto mode that's just what auto mode won't approve by itself, so prompts are rarer and
  lean toward tiers 2 and 3. The plan's targets, its tier mix and EarshotBench's "real dev" split
  (500 of your own prompts) all assume default-mode prompting.
- **Proposal:** Support auto mode as a first filter rather than treating it as a misconfiguration:
  Earshot answers whatever auto mode passes up. In Phase 1, log a week of your normal sessions'
  requests (mode, tool, would-be tier) to see how many reach Earshot per hour. Collecting the 500
  real prompts may need sessions in default mode.
- **Decide by:** before Phase 1.

### P-16 Don't route answers by spoken session name

- **Problem:** The plan lets you address a session by name ("API, yes", "the docs one"), using
  repo folder names. In Step 0 the recogniser heard "docs" as "dogs" four times and "API" as "A B
  I". Folder names are often acronyms or ordinary words, and those are exactly what it gets
  wrong. Answering the wrong session would approve the wrong request.
- **Proposal:**
  - An answer always applies to the one open approval. The floor manager already allows only one
    at a time.
  - Earshot speaks session names but never parses them to pick a request. If a reply names a
    session other than the open one, it isn't an approval: ask again.
  - Briefings can still use names, since they only read things out.
- **Decide by:** before the Phase 1 intent rules.

### P-17 Two-stage recognition: Parakeet first, Whisper when unclear

- **Problem:** On rehaan's 100 recordings, with the silence trimmed, no single recogniser met the
  plan's yes/no targets (98% quiet, 95% noisy) within its 260 ms budget:
  - Parakeet v2 got 89.5% and 94.7% in 68 ms.
  - Whisper large-v3-turbo got 100% and 89.5% in 1.1 s.
  - Parakeet v3 confused languages and false-approved a decoy.
  - Moonshine base got about 50% and looped.
- **Proposal:**
  - Parakeet v2 hears every reply (voice-activity trimmed).
  - Only when its answer is unclear, an empty transcript included, does Whisper large-v3-turbo get
    a second listen on the same audio.
  - Both are judged with the same strict rules: P-07, P-08 (revised) and P-16.
  - On the recordings: yes/no 100% in both rooms, no approvals missed, a second listen on 23 of
    100 replies, 70 ms median and 1.2 s p95. The only false approval is the deliberately
    confusable decoy, which P-08's word list rules out.
- **Costs to handle in Phase 1:**
  - The second listens add about 1.2 s; Whisper always encodes a 30-second window. Measure
    shorter windows or a smaller Whisper.
  - Memory: both models unquantised are about 3 GB of weights alone, before Kokoro. Try 8-bit
    Parakeet and 4-bit Whisper, or load Whisper only when needed.
- **Status:** Accepted at the Step 0 gate as D-017.

### P-18 Nods don't approve until a stricter detector is proven

- **Problem:** On rehaan's AirPods 4, the plan's v1 detector (two opposite swings over 1.0 rad/s
  within 1.2 s) reported 49 nods and 79 shakes in an hour of normal work, none of them deliberate.
  - Inside 6-second answer windows that's 0.8 false nods an hour at 10 tier-1 prompts an hour,
    which meets the plan's target of at most 1. But about 8% of answer windows would contain a nod
    you didn't make, and that nod would approve the request.
  - Deliberate gestures also fired several times each, and across axes.
  - Calibration (4 Nov): nodding moved x at 0.86 rad/s, with y and z under 0.1. Shaking moved z at
    2.39 but x at 0.57, two-thirds of a nod's speed, so a shake can also count as a nod. Requiring
    pitch to dominate, as below, is what separates the two.
- **Proposal:**
  - In v1.0 a nod never approves on its own. Either ship with nods off (`nods = false`), or require
    a stricter pattern: a double nod within 2 s, with pitch clearly dominating yaw and roll, after
    about a second of stillness. Re-measure with the hour-long count, aiming for under 1% of
    windows.
  - A shake never denies on its own; it hands the prompt to the screen, so a false shake costs
    nothing.
  - Record labelled `log` sessions to build the plan's gesture dataset and classifier.
- **Status:** Accepted at the Step 0 gate as D-018.

### P-19 A safety stub until the policy engine exists

- **Problem:** Phase 1 speaks requests and accepts "yes" for an answer, but the plan builds the
  policy engine (tiers, the never-by-voice floor, resolvers) and secret redaction in Phase 2. In
  between, a spoken "yes" could approve a force push, and a secret in a command could be read
  aloud or logged. That breaks two invariants: tier 3 is never approvable by voice, and secrets
  are redacted before anything is spoken or logged.
- **Proposal:** Until Phase 2's policy engine replaces it:
  - **Voice approves only an allowlist:**
    - file edits and writes inside the session's folder, except in `.git/`, `.claude/`,
      `.earshot/`, `.github/workflows/` and `.envrc`, and except build and test config
      (`conftest.py`, `package.json`, `Makefile`, `pyproject.toml`, `setup.py`), as P-01 suggests
    - single test commands (`pytest`, `uv run pytest`, `npm test`), with no chaining, pipes or
      redirection
  - **Everything else goes to the screen.** With voice on, Earshot says so briefly ("API needs
    you; it's on your screen") and doesn't listen.
  - **Secrets are redacted** by pattern before anything is spoken or logged. Phase 2 adds entropy
    detection.
- **Decide by:** before Phase 1 (milestone 1 of `docs/phase-1-plan.md`).

## Open questions

From the plan's open-questions list.

| ID  | Question                                                                       | Answered by                    | Status                                                         |
| --- | ------------------------------------------------------------------------------ | ------------------------------ | -------------------------------------------------------------- |
| Q-1 | Does Claude Code show its dialog while a `PermissionRequest` hook is still running? | Step 0 hook spike          | **Answered 4 Nov 2026 (hook probe, rehaan's Mac, Claude Code 2.1.318): yes.** The dialog appears while the hook runs, and whichever answers first wins. Approving on screen lets the tool run while the hook keeps waiting; No or Esc end the hook with SIGTERM. So presence routing isn't needed to keep the session from freezing; it only decides whether Earshot speaks at all. See P-12 and `spikes/RESULTS.md`. |
| Q-2 | How long does the AirPods mic take to switch on with the M2?                   | Step 0 audio spike             | **Answered 4 Nov 2026: 847 ms median, 931 ms max** (5 trials, `audio_io switch`). Long enough to clip the start of an answer, so the plan's fallback applies: keep the mic warm while an approval is pending, switching it on when the approval starts, while Earshot is still speaking. |
| Q-3 | Is `earshot` free on PyPI, and is "Earshot" clear enough as a name?            | rehaan                         | Partly answered. On 3 Nov 2026 `earshot` was taken by an active voice-activity-detection library (pykeio/earshot) and `earshot-ai` by a placeholder uploaded on 2 Nov 2026. `earshot-agents` was free, and D-008 adopts it. Whether the name is clear enough is still open. |
| Q-4 | Which small model clears EarshotBench in under 300 ms?                         | Phase 3                        | Open                                                           |
| Q-5 | Which 3–5 friends will record impostor and gesture data?                       | rehaan                         | Open                                                           |
| Q-6 | Release the summarizer under Apache-2.0, or match its base model's license?    | rehaan, before Phase 5         | Open                                                           |
