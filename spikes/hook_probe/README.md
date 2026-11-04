# Hook probe (Step 0)

This probe covers the plan's first Step 0 items:

- Capture real `PermissionRequest` payloads, and the other events Earshot listens to.
- Answer allow and deny from a script, and time the round trip.
- **Q-1:** find out whether Claude Code shows its own dialog while the hook is still waiting.

It runs anywhere Claude Code runs and needs no audio hardware. It uses the standard library only.

## Set up

From the repo root:

```sh
source dev/activate
uv sync
uv run python spikes/hook_probe/probe_cli.py install ~/earshot-probe
claude --version                     # note it in spikes/RESULTS.md
cd ~/earshot-probe && claude
```

`install` writes `~/earshot-probe/.claude/settings.local.json`. That hooks the probe into
`PreToolUse`, `PermissionRequest`, `PostToolUse`, `Notification`, `Stop`, `SessionStart` and
`SessionEnd` for that folder only; your own settings aren't touched. Claude Code holds back hooks
until you accept its workspace-trust prompt for the folder, so accept it.

Everything the probe sees is appended to `spikes/hook_probe/out/events.jsonl`. The file is
git-ignored and only you can read it (mode 0600). Payloads include the commands Claude runs, so
don't share the raw log.

## Runs

Switch modes from a second terminal in the repo root, after `source dev/activate` there too:

```sh
uv run python spikes/hook_probe/probe_cli.py mode <mode> [seconds]
```

The probe reads the mode on every prompt, so Claude Code doesn't need a restart.

For each run, ask Claude in the probe session for something that needs permission and isn't on
your allow list. For example: *Run this exact command: `touch probe-1.txt`*. Use a new file name
each time, so Claude never reuses an earlier approval.

**Check first:** the session must be in Claude Code's default permission mode. If the bottom of
the screen shows a mode such as "accept edits" or "auto", press Shift+Tab until none shows. In
those modes Claude Code runs commands like `touch` without asking, so the probe never gets a
`PermissionRequest`. Run 1 is the test: if no dialog appears, stop and run `report`; it says
which mode the session was in.

| # | Mode            | What you do                                    | What to note                                                  |
| - | --------------- | ---------------------------------------------- | ------------------------------------------------------------- |
| 1 | `none`          | Approve on screen                              | The dialog appears as usual                                   |
| 2 | `allow`         | Nothing                                        | The command runs with no dialog                               |
| 3 | `deny`          | Nothing                                        | Claude is told "Denied by the Earshot hook probe" and carries on |
| 4 | `hold 30`       | Watch the screen for 30 s                      | **Q-1:** does the dialog appear at once, or only after 30 s?  |
| 5 | `hold-allow 20` | If a dialog appears during the hold, choose No | Which wins: your click or the hook's late allow?              |
| 6 | `hold 60`       | Press Esc during the hold                      | How the hook ends: `report` shows a signal, or "vanished"     |
| 7 | `hold 120`      | Wait it out                                    | Whether a `permission_prompt` notification arrives during the hold |

Then:

```sh
uv run python spikes/hook_probe/probe_cli.py report --fixtures spikes/hook_probe/out/fixtures
uv run python spikes/hook_probe/probe_cli.py bench
```

What each command gives you:

- **`report`** lists each `PermissionRequest` with:
  - how long the hook ran
  - the gap from `PreToolUse` to the request
  - the gap from the decision to `PostToolUse` (the round trip)

  It also lists notifications, timed from the request, and every payload field seen per event.
- **`--fixtures`** saves one sample payload per event, with your home folder shown as `~`. Check
  them for secrets before any become test fixtures in Phase 1.
- **`bench`** times the hook process itself. The plan budgets 80 ms for hook start plus the socket
  round trip. In the Linux dev container the probe's median is about 28 ms.

## Pass criteria

- Allow and deny decisions are honoured, and no output brings up the normal dialog.
- Q-1 is answered (runs 4 and 5), along with what Esc does to a waiting hook (run 6).
- The hook process's median start time leaves room for the socket round trip inside 80 ms.

Record the numbers in [`../RESULTS.md`](../RESULTS.md), section 1.
