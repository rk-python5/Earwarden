# Earshot

Maker-checker for AI agents, in your ear. Earshot is a local macOS service that answers Claude Code
permission prompts by voice through your AirPods, with confirmation strength set by risk:

- **Tier 1:** a nod or a "yes".
- **Tier 2:** a random challenge word plus your voiceprint.
- **Tier 3:** keyboard only, never by voice.

Everything runs on your Mac: no cloud calls at runtime, and no account or API key of its own.

## Status

Pre-alpha. Step 0 (feasibility) is in progress, and nothing is installable yet. The spike kits
are in [spikes/](spikes/), and their results feed the go/no-go note,
[spikes/RESULTS.md](spikes/RESULTS.md). The
[build plan](docs/design/earshot-technical-design-build-plan.pdf) lays out the road to v1.0.

## Documents

- [Technical design and build plan](docs/design/earshot-technical-design-build-plan.pdf)
- [Decisions](decisions.md): decisions, proposals and open questions
- [Changelog](CHANGELOG.md)
- [CLAUDE.md](CLAUDE.md): working rules for Claude Code sessions in this repo

## Development

You need [uv](https://docs.astral.sh/uv/); it fetches Python 3.11 if you don't have it.

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

The PyPI distribution will be `earshot-agents`; the import name and commands stay `earshot`.

## License

Apache-2.0. See [LICENSE](LICENSE).
