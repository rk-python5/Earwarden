# Privacy

**Does Earshot read my code aloud?** Not file contents. It says what's being asked in a short
sentence: the tool, the project's name and the critical fields of the request (a file's name, a
package, a branch). Secrets in a command are redacted before they're spoken or logged. A long
or odd value is spelled out letter by letter, or sent to the screen.

**What leaves my Mac?** Nothing while it runs. There's no account, no API key and no telemetry.
It downloads things only at setup: spaCy's model from GitHub, the voiceprint model from this
project's release, and the speech models from Hugging Face on first start.

**Is my voice stored?** Audio isn't kept. With `earshotd --keep-audio` (for tuning) each
answer's clip is saved in Earshot's folder, and it stays there until you delete it. Your enrolled
voiceprint is a set of numbers, not a recording, kept in a file only you can read.

**What's logged?** One line per decision: when, which session and tool, the outcome and why, what
the recogniser heard, and the voiceprint score, in a tamper-evident chain. Secrets are redacted
first.

**What can see the microphone?** Only the helper app, `Earshot`, which macOS lists in
System Settings, Privacy & Security. It listens while a question is open or you've asked to talk,
and stops when the answer window ends.
