# Earshot

Maker-checker for AI agents, in your ear. Earshot is a local macOS service that answers Claude Code
permission prompts by voice through your AirPods, with confirmation strength set by risk:

- **Tier 1:** a nod or a "yes".
- **Tier 2:** a random challenge word plus your voiceprint.
- **Tier 3:** keyboard only, never by voice.

Everything runs on your Mac: no cloud calls at runtime, and no account or API key of its own.

## Install

You need a Mac with Apple Silicon (macOS 14 or later), AirPods or another headset,
[uv](https://docs.astral.sh/uv/), Claude Code and Xcode's command line tools:

```sh
uv tool install 'earshot-agents[voice]'
earshot setup      # hooks, the helper app, and the voice models
earshot enroll     # your voiceprint, about 3 minutes with the AirPods in
earshot service install --voice --stem
```

[docs/quickstart.md](docs/quickstart.md) has the five-minute version with what to expect. Without
`[voice]`, or without a headset, every prompt stays on Claude Code's screen, as it always has.

## Status

Earshot 1.0 passed its test suite, a red-team suite and recorded-audio checks, and has run live
on one setup: an M2 MacBook Air with AirPods 4 and one speaker's voice. Other headsets, rooms and
voices are untested, and the voiceprint's threshold isn't calibrated on other people. Voice is a
convenience check, never identity proof, and tier 3 is never approvable by voice. Read
[SECURITY.md](SECURITY.md) for what it does and doesn't promise, and
[docs/redteam.md](docs/redteam.md) for the attacks it was tried against. Until
P-20 in [decisions.md](decisions.md) closes after longer use, try voice in a scratch project
first.

## Documents

- [Quick start](docs/quickstart.md), [how tiers work](docs/how-tiers-work.md) and
  [privacy](docs/privacy.md)
- [SECURITY.md](SECURITY.md), the [red-team table](docs/redteam.md) and
  [attribution](docs/attribution.md) for every model and library
- [Technical design and build plan](docs/design/earshot-technical-design-build-plan.pdf)
- [Decisions](decisions.md): decisions, proposals and open questions
- [Changelog](CHANGELOG.md)
- [Releasing](docs/releasing.md) and [CLAUDE.md](CLAUDE.md): working rules for maintainers and
  Claude Code sessions in this repo

## Development

Everything Earshot installs stays inside this folder, in venvs: uv itself, the Python 3.11 it
downloads, every library and every model. Nothing goes into your system or shell profile
(decisions.md, D-013). In each new terminal, from the repo:

```sh
source dev/activate
```

The first time, this puts uv into a venv in `.tools/` using your Mac's `python3`. Then:

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

To remove everything, delete `.tools/` and `.venv/`.

The PyPI distribution is `earshot-agents`; the import name and commands are `earshot`.

## License

Apache-2.0. See [LICENSE](LICENSE).
