# Changelog

All notable changes to Earshot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow Semantic Versioning,
written in PEP 440 form (see D-006 in [decisions.md](decisions.md)).

## [Unreleased]

### Added

- `dev/activate`, sourced once per terminal on the Mac. It keeps uv, the Python it downloads, every
  library, the spike scripts' environments and model downloads inside the repo, under the
  git-ignored `.tools/` (D-013).
- First Step 0 results, from the hook probe on rehaan's Mac (`spikes/RESULTS.md`, section 1). Allow
  and deny from a hook work, and Q-1 is answered: Claude Code shows its own dialog while the hook is
  still running, and whichever answers first wins. P-12 is revised to match, and P-15 (auto mode)
  is new.

### Changed

- Setup instructions use `source dev/activate` instead of installing uv system-wide.
- The hook probe report credits each tool run to its own request, even when a refused command is
  asked for again. It also says who decided: the hook, or you on screen.

## [0.0.1] - 2026-11-03

The Step 0 kit: project conventions, the package scaffold, CI, and the feasibility spikes ready to
run on the Mac.

### Added

- Technical design and build plan (revision of 3 Nov 2026) in `docs/design/`.
- `CLAUDE.md`, `decisions.md` and this changelog.
- Python package scaffold: distribution `earshot-agents`, import name `earshot`, managed with uv on
  Python 3.11, checked with ruff, strict mypy and pytest.
- Tests that keep the version, the changelog and the installed metadata in step, and that keep
  `import earshot` free of other imports.
- CI on GitHub Actions (macOS 15, Apple Silicon): lint, format, strict types and tests on every push
  to `main`.
- Step 0 hook probe (`spikes/hook_probe`): a stdlib-only Claude Code hook. It logs every event,
  answers `PermissionRequest` with none, allow, deny or a timed hold, and comes with tools to
  install it in a scratch project, time it and report the round trip. It answers Q-1. Results go in
  `spikes/RESULTS.md`, the go/no-go note.
- Step 0 speech spike (`spikes/speech`):
  - Kokoro time to first audio.
  - A 50-reply recording kit, with decoy and negation replies, for quiet and noisy rooms.
  - Parakeet evaluation with a per-word confidence score and a false-approval count.
  - A pronunciation-coverage check that runs on any OS. Its first result: without espeak-ng, 47.6%
    of the top 1,000 PyPI names would be skipped in speech.
- Step 0 AirPods I/O spike (`spikes/audio_io`): mic switch delay (Q-2), playback leak and
  output-to-mic delay, and a self-approval check (P-06).
- Step 0 launchd microphone check (`spikes/launchd_mic`): runs a mic recording as a one-off launchd
  agent and from Terminal, to see whether macOS grants the mic and whether the grant survives an
  interpreter change (P-13).
- Step 0 head-motion spike (`spikes/motion`): a Swift command-line tool on `CMHeadphoneMotionManager`.
  It has three modes: `calibrate` finds the nod and shake axes, `count` counts false nods over an
  hour of normal work with the plan's v1 detector, and `log` streams JSON lines. CI builds it on
  macOS.
- Step 0 voiceprint spike (`spikes/voiceprint`): ECAPA scores for your phrases against a friend's,
  with the gap between them. It also exports ECAPA to ONNX, checks parity with PyTorch at every
  phrase length, and measures an onnxruntime-only process.
- The go/no-go note (`spikes/RESULTS.md`) maps the plan's four week-1 tests to the spike sections
  and lists what gets decided at the gate.

[Unreleased]: https://github.com/rk-python5/Earshot/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/rk-python5/Earshot/releases/tag/v0.0.1
