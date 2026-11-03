# Changelog

All notable changes to Earshot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow Semantic Versioning,
written in PEP 440 form (see D-006 in [decisions.md](decisions.md)).

## [Unreleased]

### Added

- Technical design and build plan (revision of 3 Nov 2026) in `docs/design/`.
- `CLAUDE.md`, `decisions.md` and this changelog.
- Python package scaffold: distribution `earshot-agents`, import name `earshot`, version
  `0.0.1.dev0`, managed with uv on Python 3.11, checked with ruff, strict mypy and pytest.
- Tests that keep the version, the changelog and the installed metadata in step, and that keep
  `import earshot` free of other imports.
- CI on GitHub Actions (macOS 15, Apple Silicon): lint, format, strict types and tests on every push
  to `main`.
- Step 0 hook probe (`spikes/hook_probe`): a stdlib-only Claude Code hook. It logs every event,
  answers `PermissionRequest` with none, allow, deny or a timed hold, and comes with tools to
  install it in a scratch project, time it and report the round trip. It answers Q-1. Results go in
  `spikes/RESULTS.md`, the go/no-go note.
