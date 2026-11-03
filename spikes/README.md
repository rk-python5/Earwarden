# Step 0 spikes

Week-1 feasibility checks from the build plan. Each spike is a small, self-contained kit: scripts,
a README with the exact steps, and a section in [RESULTS.md](RESULTS.md), the go/no-go note, to
fill in with numbers. The Step 0 gate passes when all four week-1 tests pass and are written up
there.

| Spike                     | Plan items covered                                   | Runs on                     |
| ------------------------- | ---------------------------------------------------- | --------------------------- |
| [hook_probe](hook_probe/) | Real `PermissionRequest` payload, allow and deny from a script, round-trip time, Q-1 | Any machine with Claude Code |

Conventions:

- **Dependencies:** scripts declare their own inline (PEP 723) and run with `uv run`, so heavy,
  macOS-only libraries stay out of the project's lock file. The hook probe needs nothing beyond
  the standard library.
- **Output:** recordings, logs and raw measurements go to each spike's `out/` folder, which is
  git-ignored. Only the summary numbers go into `RESULTS.md`.
- **Results authorship:** results rehaan writes up are committed under rehaan's name (D-005).
