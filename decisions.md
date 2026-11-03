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
| D-005 | Commit authorship                                         | Accepted |
| D-006 | Versioning                                                | Accepted |
| D-007 | Living project docs: CLAUDE.md, decisions.md, CHANGELOG.md | Accepted |
| D-008 | Distribution name `earshot-agents`, import name `earshot` | Accepted |
| D-009 | Tooling: uv, Python 3.11, ruff, mypy, pytest              | Accepted |
| D-010 | CI on GitHub-hosted macOS 15, Apple Silicon               | Accepted |

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

- **Date:** 2026-11-03 · **Status:** Accepted · **By:** rehaan
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
  - It runs on `macos-15`. GitHub retired the `macos-14` image on 2026-11-02, so macOS 14, the
    plan's minimum, can only be tested on a real Mac.
  - Third-party actions are pinned to a commit SHA; GitHub's own actions to a major version.
- **Consequences:** Hosted runners have no Metal (see P-14), so jobs that need MLX models will need
  a self-hosted runner.

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
- **Decide by:** Step 0 gate.

### P-06 Earshot must not hear itself approve

- **Problem:** The tier-2 prompt ends with the exact answer ("say: approve orchard"). Bluetooth
  keeps playing after the Mac finishes sending audio, and the 1.5 s pre-roll can contain the tail of
  Earshot's own voice. Any leak into the mic can be transcribed as the answer. At tier 1 nothing
  else stands in the way.
- **Proposal:**
  - Open the answer window only after playback has really ended, plus the measured output delay.
  - Never take pre-roll from before the window opened.
  - Add "Earshot hears itself" to the red-team suite. Step 0 measures it (`spikes/audio_io`).
- **Decide by:** Step 0 gate.

### P-07 Approve only on an exact whole-utterance match

- **Problem:** "Do it" is an approval phrase, and it's contained in "don't do it" and "do it
  later". Recognisers also drop short words like "don't".
- **Proposal:** Approval needs the whole utterance to match a short list exactly. Any negation or
  extra word means no approval: deny, instruction or ask again.
- **Decide by:** before the Phase 1 intent rules.

### P-08 Challenge-word matching

- **Problem:** Double Metaphone codes "orchard" as ARXRT/ARKRT and "orchid" as ARKT, one edit
  apart; "orchards" and "archer" are also one edit away. Any edit-distance allowance on the codes
  lets "orchid" through, so the plan's own example fails.
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

- **Problem:** Presence is checked once, before speaking. If the dialog waits for the hook (Q-1),
  a user who comes back mid-wait sees a frozen session for up to 90 s. A hook that Claude Code kills
  (Esc, timeout, session end) leaves the daemon asking about a request that no longer exists, and
  the next answer can land on the wrong one.
- **Proposal:**
  - Keyboard activity during a wait hands off at once.
  - A closed hook socket cancels its approval.
  - While the user is away, hold for close to the hook timeout and re-announce, instead of handing
    off at 90 s.
  - Register unknown sessions lazily from any request.
  - The audit log records that in sessions that can't show a prompt, "no output" means deny.
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
- **Decide by:** Step 0 gate.

### P-14 Audio integration tests on a self-hosted runner

- **Problem:** GitHub-hosted Apple Silicon runners don't expose Metal, so the plan's integration
  layer (recorded replies through MLX models) probably can't run there.
- **Proposal:** Run that layer on rehaan's M2 as a self-hosted runner. Hosted macOS runners keep
  the unit, property and end-to-end layers.
- **Decide by:** before the Phase 1 integration tests.

## Open questions

From the plan's open-questions list.

| ID  | Question                                                                       | Answered by                    | Status                                                         |
| --- | ------------------------------------------------------------------------------ | ------------------------------ | -------------------------------------------------------------- |
| Q-1 | Does Claude Code show its dialog while a `PermissionRequest` hook is still running? | Step 0 hook spike          | Open. The hooks docs say the hook "runs when Claude Code is about to ask you for permission", which suggests the dialog waits for it. |
| Q-2 | How long does the AirPods mic take to switch on with the M2?                   | Step 0 audio spike             | Open                                                           |
| Q-3 | Is `earshot` free on PyPI, and is "Earshot" clear enough as a name?            | rehaan                         | Partly answered. On 3 Nov 2026 `earshot` was taken by an active voice-activity-detection library (pykeio/earshot) and `earshot-ai` by a placeholder uploaded on 2 Nov 2026. `earshot-agents` was free, and D-008 adopts it. Whether the name is clear enough is still open. |
| Q-4 | Which small model clears EarshotBench in under 300 ms?                         | Phase 3                        | Open                                                           |
| Q-5 | Which 3–5 friends will record impostor and gesture data?                       | rehaan                         | Open                                                           |
| Q-6 | Release the summarizer under Apache-2.0, or match its base model's license?    | rehaan, before Phase 5         | Open                                                           |
