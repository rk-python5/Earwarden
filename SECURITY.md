# Security

Earwarden answers permission prompts for a coding agent, so a flaw in it can approve something you
didn't mean to. Please report one privately before you tell anyone else.

## Reporting a problem

Use GitHub's private vulnerability reporting: the **Security** tab of
<https://github.com/rk-python5/Earwarden>, then **Report a vulnerability**. Please include the
Claude Code version, what Earwarden said, what was said back (or played at it), and what it did.
I'll answer as soon as I can. Fixes are released as patch versions, and the report is
credited in the changelog unless you'd rather it wasn't.

Anything that gets an approval through the red-team table (`docs/redteam.md`) is a vulnerability,
and so is any way for tier 3, or a hook failure, to end in an approval instead of the screen.

## What Earwarden promises

- **It fails toward the screen.** Any error, doubt, timeout or unrecognised input ends with Claude
  Code's own dialog. Earwarden never approves by default.
- **Tier 3 is never approvable by voice.** Rules decide the tier, from the command itself. A
  model can reword speech, but it can never choose a tier, and a risk score can only raise one.
- **Tier 2 needs the right word and the right voice.** A fresh challenge word, said by a voice that
  matches your enrolled voiceprint.
- **Nothing leaves your Mac when it runs.** Models download once, at setup. Audio isn't stored
  unless you start the daemon with `--keep-audio`, and secrets are redacted before anything is
  spoken or logged.
- **Every decision is logged, tamper-evidently:** a keyed hash chain, with its end anchored outside
  the file. `earwarden audit verify` checks it.

## What it doesn't promise

The threat model is in `docs/redteam.md`. In short:

- **Voice is a convenience check, not identity proof.** A good enough recording or clone of your
  voice that also says the fresh challenge word can pass tier 2. Tier 3 never relies on voice.
- **It has been tested on one setup:** an M2 MacBook Air, AirPods 4 with noise cancelling, and one
  speaker's voice, with a few friends' recordings. Other headsets, rooms and voices may behave
  differently. The voiceprint threshold (0.50) hasn't been calibrated on other people.
- **A person at your keyboard** can approve on screen as always. At the keyboard, Earwarden stays
  quiet.
- **The helper app is signed ad hoc**, not with an Apple Developer ID, because it's built on your
  own Mac by `earwarden setup`. macOS asks for the microphone and head-motion permission once, in
  Earwarden's name, and again if the helper is rebuilt.
