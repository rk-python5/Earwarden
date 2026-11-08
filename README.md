# Earshot

Maker-checker for AI agents, in your ear. Earshot is a local macOS service that answers Claude Code
permission prompts by voice through your AirPods, with confirmation strength set by risk:

- **Tier 1:** a nod or a "yes".
- **Tier 2:** a random challenge word plus your voiceprint.
- **Tier 3:** keyboard only, never by voice.

Everything runs on your Mac: no cloud calls at runtime, and no account or API key of its own.

## Status

Pre-alpha, and nothing is installable yet. Step 0 (feasibility) passed its gate on
4 Nov 2026. The spike kits are in [spikes/](spikes/), and their results are in the go/no-go note,
[spikes/RESULTS.md](spikes/RESULTS.md). Phase 1, the walking skeleton, passed its gate on
8 Nov 2026: a Claude Code permission prompt was answered by voice through AirPods, end to end,
under a safety stub. Phase 2, the safety layer, is next. Until it fixes how the recogniser hears
non-speech (P-20 in [decisions.md](decisions.md)), use voice only in a scratch project. The
[build plan](docs/design/earshot-technical-design-build-plan.pdf) lays out the road to v1.0.

## Documents

- [Technical design and build plan](docs/design/earshot-technical-design-build-plan.pdf)
- [Decisions](decisions.md): decisions, proposals and open questions
- [Changelog](CHANGELOG.md)
- [CLAUDE.md](CLAUDE.md): working rules for Claude Code sessions in this repo

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

The PyPI distribution will be `earshot-agents`; the import name and commands stay `earshot`.

## License

Apache-2.0. See [LICENSE](LICENSE).
