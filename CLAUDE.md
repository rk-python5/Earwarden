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

Step 0 (week 1, feasibility) is in progress. Its gate: all four week-1 spikes pass, written up with
numbers.

A phase starts only after the previous gate is recorded as passed in `decisions.md`. Don't build
Phase 1 components (daemon, contracts, policy engine and so on) before then.

## Working rules (set by rehaan)

- **Branch:** work on `main` only. No feature branches or pull requests. Push with
  `git push -u origin main`.
- **Commits:** one coherent change per commit, never mixed with unrelated changes. Update
  `decisions.md`, `CHANGELOG.md`, `README.md` and this file in the same commit as the change they
  describe.
- **Authorship:** material rehaan provides (docs, results, notes) is committed with
  `--author="rehaan <108854279+rk-python5@users.noreply.github.com>"` so it counts on their GitHub
  profile. Claude's own work uses the session identity.
- **Versioning:** follows D-006 in `decisions.md`. The version lives only in `pyproject.toml`;
  change it with `uv version` (for example `uv version --bump patch`). Every notable change gets a
  line under *Unreleased* in `CHANGELOG.md`. `tests/test_versioning.py` keeps the two in step.

## Releasing

Cut a release only when rehaan asks, or when a phase's gate passes (D-006).

1. In `CHANGELOG.md`, rename *Unreleased* to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty
   *Unreleased* above it, and update the compare links at the bottom.
2. Run `uv version X.Y.Z`, then run the checks.
3. Commit as "Release X.Y.Z", tag it with `git tag -a vX.Y.Z -m "…"`, and push the commit and
   the tag.
4. Run `uv version X.Y.(Z+1).dev0` and commit "Start X.Y.(Z+1) development", so `main` never
   carries a released version number.

## Commands

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

- `docs/design/`: the spec (PDF).
- `src/earshot/`: the package. The PyPI name is `earshot-agents` (D-008). Keep
  `src/earshot/__init__.py` free of imports; a test enforces it.
- `spikes/`: Step 0 feasibility kits. Each has a README with steps, and results go in
  `spikes/RESULTS.md`. Spike scripts declare their dependencies inline (PEP 723) and run with
  `uv run`. Their raw output goes to a git-ignored `out/` folder. Only their stdlib and
  pure-Python parts (`spikes/hook_probe`, `speech_data.py`, `launchd_mic/agent.py`) are
  type-checked and tested in CI, because the rest need macOS hardware.
- `tests/`: pytest. Tests for spikes live in `tests/spikes/`.

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
