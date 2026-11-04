# CLAUDE.md

Guidance for Claude Code sessions in this repository. Update it in the same commit as any change
to the rules, commands or layout it describes.

## Project

Earshot is a local macOS service that answers Claude Code permission prompts by voice through
AirPods, with confirmation strength set by risk tier. Tier 3 is never approvable by voice.

- **Spec:** `docs/design/earshot-technical-design-build-plan.pdf` (revision of 3 Nov 2026). It's
  the baseline.
- **Decisions, proposals and open questions:** `decisions.md`. Read it before changing anything the
  spec covers, and record new decisions there.
- **Notable changes:** `CHANGELOG.md`.

## Status

Step 0 (week 1, feasibility) passed its gate on 4 Nov 2026 (D-014). Its results are in
`spikes/RESULTS.md`, and the decisions taken at the gate are D-014 to D-018.

Phase 1 (weeks 2–3, the walking skeleton) is next. Its gate: a real Claude Code session on
rehaan's subscription, approved by voice end to end. Its scope is the plan's Phase 1 list, plus the
helper app's mic capture and device changes (D-016) and two-stage recognition (D-017). The build
order, milestones and the decisions each one needs are in `docs/phase-1-plan.md`. Mark milestones
done there as they finish.

A phase starts only after the previous gate is recorded as passed in `decisions.md`. Don't build
Phase 2 components (policy engine, resolvers, challenge words, voiceprint, nod detector and so on)
before Phase 1's gate passes.

## Working rules (set by rehaan)

- **Branch:** work on `main` only. No feature branches or pull requests. Push with
  `git push -u origin main`.
- **Commits:** one coherent change per commit, never mixed with unrelated changes. Update
  `decisions.md`, `CHANGELOG.md`, `README.md` and this file in the same commit as the change they
  describe.
- **Authorship (D-012):** every commit is authored by rehaan, so it counts on the `rk-python5`
  GitHub profile. Before your first commit in a session, run:

  ```sh
  git config author.name "rehaan"
  git config author.email "108854279+rk-python5@users.noreply.github.com"
  ```

  Leave the committer as the session identity, because it signs the commits. Keep ending each
  message with the `Co-Authored-By` trailer for Claude.
- **Explaining:** whenever you ask rehaan to run something, explain each command: what it does,
  why it's needed, what to watch for, and roughly how long it takes. Never hand over bare
  commands.
- **Versioning:** follows D-006 in `decisions.md`. The version lives only in `pyproject.toml`;
  change it with `uv version` (for example `uv version --bump patch`). Every notable change gets a
  line under *Unreleased* in `CHANGELOG.md`. `tests/test_versioning.py` keeps the two in step.

## Releasing

Cut a release only when rehaan asks, or when a phase's gate passes (D-006).

1. In `CHANGELOG.md`, rename *Unreleased* to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty
   *Unreleased* above it, and update the compare links at the bottom.
2. Run `uv version X.Y.Z`, then run the checks.
3. Commit as "Release X.Y.Z", tag it with `git tag -a vX.Y.Z -m "…"`, and push the commit and
   the tag. Cloud sessions can push `main` but not tags: GitHub answers HTTP 403, so don't
   retry. Instead, ask rehaan to run
   `git fetch origin && git tag -a vX.Y.Z <release commit> -m "…" && git push origin vX.Y.Z` from
   their clone. To check the tag arrived, use the GitHub API (the `list_tags` tool). From a cloud
   session, `git ls-remote` doesn't show tags even when they exist.
4. Run `uv version X.Y.(Z+1).dev0` and commit "Start X.Y.(Z+1) development", so `main` never
   carries a released version number. After the release that closes a phase, start the next
   phase's minor instead: `0.(N+1).0.dev0`, as 0.0.2 was followed by `0.1.0.dev0` (D-006).

## Commands

On rehaan's Mac, every install stays inside the repo, in venvs (D-013). Start each terminal there
with `source dev/activate`, and never suggest system-wide installs (no `curl | sh`, no
`brew install`, no global `pip`). Cloud containers already have uv and don't need it.

```sh
uv sync                        # create .venv with the dev tools (Python 3.11)
uv run ruff check .            # lint
uv run ruff format --check .   # formatting (drop --check to apply)
uv run mypy                    # strict type check of src/ and tests/
uv run pytest                  # tests
```

Run all four before every push. CI (`.github/workflows/ci.yml`, macOS 15 on Apple Silicon) runs
the same checks on every push to `main`. It also builds the Swift spike in `spikes/motion`. That's the only place it
compiles when you work in the Linux container, so check the CI run after changing Swift code.

## Layout

- `dev/activate`: sourced per terminal on the Mac. It keeps uv, its Python, caches, spike
  environments and model downloads in the git-ignored `.tools/` (D-013).
- `docs/design/`: the spec (PDF).
- `docs/phase-1-plan.md`: the Phase 1 build plan, with milestones and the decisions each needs.
- `src/earshot/`: the package. The PyPI name is `earshot-agents` (D-008). Keep
  `src/earshot/__init__.py` free of imports; a test enforces it.
  - `contracts.py`: the five messages as Pydantic models, at version 1.
  - `wire.py` and `paths.py`: the wire format and file locations that the hook and the daemon
    share. Standard library only.
  - `connectors/claude_code/hook.py`: `earshot-hook`. Standard library only; a test checks its
    imports.
  - `cli.py`: the `earshot` command (`init`, `uninstall`, `observe`). `stub.py`: the safety
    stub (D-019) that limits what voice may approve until Phase 2.
  - `audit.py`: the keyed, hash-chained audit log (D-025) behind `earshot audit verify`.
  - `narrator/`: the template narrator, spoken forms, and secret redaction.
  - `connectors/claude_code/settings.py`: adds and removes Earshot's hooks in a Claude Code
    settings file, with a byte-for-byte backup.
  - `voice/`: the voice decider and intent rules (testable anywhere), presence by keyboard idle
    time, and `mac.py`, which speaks and listens with Kokoro, Parakeet and Whisper (macOS only;
    `uv sync --group voice`).
  - `daemon/`: `earshotd`, the background service. `server.py` is the socket server, `state.py`
    the sessions and waiting requests, `cli.py` the command. `auth.py` keeps the shared token.
- `spikes/`: Step 0 feasibility kits. Each has a README with steps, and results go in
  `spikes/RESULTS.md`. Spike scripts declare their dependencies inline (PEP 723) and run with
  `uv run`. Their raw output goes to a git-ignored `out/` folder. Only their stdlib and
  pure-Python parts (`spikes/hook_probe`, `speech_data.py`, `speech/combine.py`,
  `launchd_mic/agent.py`) are
  type-checked and tested in CI, because the rest need macOS hardware.
- `tests/`: pytest. Tests for spikes live in `tests/spikes/`.
  `tests/fixtures/claude_code/<version>/` holds real Claude Code hook payloads, with the home
  folder shortened. Capture a new set when Claude Code changes its hook format.

## Invariants

These come from the spec and the Claude Code hooks reference. Don't break one without a decision
entry.

- **Fail toward the screen.** Any error, doubt, timeout or unrecognised input ends with the hook
  printing nothing, so Claude Code shows its normal dialog. Earshot never approves by default.
- **The hook client is minimal.** `earshot-hook` uses only the standard library, always exits 0, and
  never prints anything except one final decision object on `PermissionRequest`. This matters
  because:
  - Exit code 2 isn't honoured on `PermissionRequest`, but on `Stop` it keeps Claude running, and
    argparse exits 2 on a bad flag.
  - On `SessionStart`, anything printed becomes Claude's context.
- **Rules decide tiers.** Tier 3 is never approvable by voice. Models never decide a tier; they only
  reword speech, and the checker can only make speech plainer.
- **Nothing leaves the Mac at runtime.** Audio isn't stored by default. Secrets are redacted before
  anything is spoken or logged.
- **Python 3.11.** No 3.12+ syntax or standard-library APIs.

## Platform

Sessions may run in a Linux container (cloud) or on rehaan's Mac (M2, 16 GB, macOS 14+). MLX,
CoreAudio, CoreMotion and Swift exist only on macOS on Apple Silicon:

- Import them lazily, and skip their tests on other platforms.
- rehaan runs the hardware measurements. Claude prepares the scripts, instructions and result
  templates.
