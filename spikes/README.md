# Step 0 spikes

Week-1 feasibility checks from the build plan. Each spike is a small, self-contained kit: scripts,
a README with the exact steps, and a section in [RESULTS.md](RESULTS.md), the go/no-go note, to
fill in with numbers. The Step 0 gate passes when all four week-1 tests pass and are written up
there.

| Spike                     | Plan items covered                                   | Runs on                     |
| ------------------------- | ---------------------------------------------------- | --------------------------- |
| [hook_probe](hook_probe/) | Real `PermissionRequest` payload, allow and deny from a script, round-trip time, Q-1 | Any machine with Claude Code |
| [speech](speech/)         | Kokoro and Parakeet on the M2, time to first audio, 100 recorded replies (quiet and noisy); P-03, P-05, P-07, P-08 | macOS on Apple Silicon; pronunciation check anywhere |
| [audio_io](audio_io/)     | AirPods mic switch delay (Q-2), playback leak into the mic; P-06 self-approval | macOS with AirPods |
| [launchd_mic](launchd_mic/) | Addition: mic permission for a launchd-started Python (P-13) | macOS |
| [motion](motion/)         | `CMHeadphoneMotionManager` in Swift, false nods over an hour of normal work | macOS 14+, Xcode, head-tracking AirPods |
| [voiceprint](voiceprint/) | ECAPA on 10 of your phrases and 10 of a friend's, the gap; ONNX parity | Any OS; written for the M2 |

Conventions:

- **Dependencies:** scripts declare their own inline (PEP 723) and run with `uv run`, so heavy,
  macOS-only libraries stay out of the project's lock file. The hook probe needs nothing beyond
  the standard library.
- **Output:** recordings, logs and raw measurements go to each spike's `out/` folder, which is
  git-ignored. Only the summary numbers go into `RESULTS.md`.
- **Authorship:** every commit, results included, is authored by rehaan (D-012).
