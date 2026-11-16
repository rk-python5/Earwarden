# Quick start

Five minutes of your time, plus the downloads. You need a Mac with Apple Silicon (macOS 14 or
later), AirPods or another headset, [uv](https://docs.astral.sh/uv/), Claude Code, and Xcode's
command line tools (`xcode-select --install`, if `swift --version` doesn't answer).

## 1. Install

```sh
uv tool install 'earshot-agents[voice]'
earshot setup
```

`earshot setup` adds Earshot's hooks to `~/.claude/settings.json` (the file as it was is saved
beside it, and `earshot uninstall` puts it back), builds the helper app that listens through your
AirPods, installs spaCy's English model and downloads the voiceprint model. The first voice start
downloads the speech models (about 4 GB, once). If a step fails it says which, and running
`earshot setup` again redoes only what's missing.

macOS asks to let **Earshot** use the microphone and head motion the first time. Allow both.

## 2. Enrol your voice

With your AirPods in:

```sh
earshot enroll
```

You say 18 short phrases (about 3 minutes). This is what tier 2 checks against. It stays on your
Mac, readable only by you.

## 3. Start it

```sh
earshot service install --voice --stem
earshot doctor
```

This starts Earshot at login. `--stem` makes a press of the AirPods stem open a command window
("status", "repeat", "details", "quiet mode") but stops the stem playing or pausing music; leave
it off if you'd rather keep that. `earshot doctor` lists what's in place and what isn't.

## 4. Try it

```sh
earshot test               # a harmless request, answered by "yes" or "no"
earshot test --tier 2      # a stricter one: say "approve", then the word it asks for
```

Then use Claude Code as usual. Earshot speaks only when you're away from the keyboard and your
AirPods are the output. At the keyboard, prompts stay on screen.

## Day to day

- Answer a question with **yes**, **no**, or **no, use X instead** (the instruction goes to the
  agent). Say **wait** to move it to the screen. A head shake moves it to the screen too.
- Press the stem (or run `earshot talk`) for a command: **status**, **repeat**, **details**,
  **stop**, **quiet mode**, **focus mode**, **chatty mode**.
- `earshot mode quiet|focus|chatty` sets how much Earshot announces; `earshot status` shows the
  sessions.
- `earshot audit tail` shows recent decisions, and `earshot audit verify` checks the log.
- `earshot service uninstall` and `earshot uninstall` take Earshot out again.

If anything is unclear or broken, Earshot's answer is always the same: the prompt stays on your
screen. Nothing is ever approved because Earshot couldn't tell.
