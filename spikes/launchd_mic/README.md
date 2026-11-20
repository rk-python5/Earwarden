# Microphone access under launchd (Step 0)

This is a short check added from the design review (P-13). `earwardend` will be started at login by
a launchd agent, as a Python interpreter from a uv-managed environment. It needs the microphone,
and macOS ties microphone permission to the binary that asks for it. This check answers:

1. Can a Python process started by launchd get the microphone at all, and does macOS show a
   prompt?
2. What name does the prompt show? A bare "python3.11" means nothing to a user.
3. Does the permission survive a change of interpreter, as happens when uv upgrades Python?

The answers decide whether the mic should move into a small signed helper app (P-13). Needs macOS.
Run from the repo root after `source dev/activate`: `setup` uses uv to build the test venv in
`out/`. The script itself uses only the standard library, so your Mac's `python3` runs it.

```sh
python3 spikes/launchd_mic/agent.py setup                      # venv with sounddevice and numpy
python3 spikes/launchd_mic/agent.py --device AirPods run       # start under launchd
python3 spikes/launchd_mic/agent.py --device AirPods terminal  # same check from Terminal
```

`run` loads the agent from `out/` for one run and unloads it again. Nothing is installed in
`~/Library/LaunchAgents`. Each run prints the interpreter's real path and a verdict:

- **audio came through:** the mic worked.
- **denied (silence):** exact zeros, which usually means macOS refused without asking.
- **error:** with the message.

Then simulate an interpreter upgrade and run again:

```sh
python3 spikes/launchd_mic/agent.py setup --python 3.12
python3 spikes/launchd_mic/agent.py --device AirPods run
python3 spikes/launchd_mic/agent.py clean
```

Note whether macOS asks again. You can see and reset what was granted in System Settings → Privacy
& Security → Microphone.

Record the answers in [`../RESULTS.md`](../RESULTS.md), section 4.
