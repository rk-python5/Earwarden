# Head motion (Step 0)

This spike covers the plan's item: prototype `CMHeadphoneMotionManager` in Swift and count false
nods over an hour of normal work. It's a small command-line tool that reads your AirPods' head
motion and runs the plan's v1 detector: two rotation-rate swings of opposite sign within 1.2 s
make a nod (pitch) or a shake (yaw).

You need:

- macOS 14 or later
- Xcode 15 or later, or Apple's Command Line Tools (anything that provides `swift`)
- AirPods with head tracking (AirPods Pro, Max, AirPods 3rd generation or later, or AirPods 4),
  connected to the Mac

CI builds the tool on every push, so you know it compiles.

**Always start it with `run.sh`, not by running the program directly.** macOS judges a program by
the app responsible for it. Started straight from Terminal, the spike counts as Terminal's, and
Terminal declares no use of motion data. So macOS stops it with a bare `abort` as soon as it asks
for head motion, which is exactly what happened on rehaan's Mac. `run.sh` does three things:

1. Builds the tool and wraps it in a small app, `.build/MotionSpike.app`, with its own name and
   usage text.
2. Signs it for this Mac only.
3. Opens it as its own app, with its output in your terminal.

```sh
cd spikes/motion
./run.sh calibrate
```

The first run makes macOS ask for motion access for "Earshot motion spike"; allow it. If you
denied it by mistake, allow it in System Settings → Privacy & Security → Motion & Fitness.

## 1. Calibrate (1 minute)

`calibrate` first waits for motion to arrive from the AirPods. The stream can take a few seconds to
settle, and it gives up after 30 s. Once it prints "Motion is flowing", nod five times, then shake
your head five times when it asks. It reports each axis's typical speed in rad/s and which axis
carries each gesture. If they aren't `x` for nods and `z` for shakes, pass `--pitch-axis` and
`--yaw-axis` to the other commands. Then try some deliberate nods and shakes:

```sh
./run.sh count --minutes 2      # nod and shake a few times; all detected?
```

If small nods are missed, lower `--threshold` (rad/s, default 1.0). If one swing counts twice,
raise it.

## 2. False nods over an hour of normal work

```sh
./run.sh count --minutes 60
```

Work normally: type, read, drink, talk, turn to look at things. Don't nod on purpose. Every
detected gesture is a false positive. It prints a summary every 5 minutes and at the end, with
false nods per hour.

The plan only counts gestures inside 6-second answer windows after tier-1 prompts, so the summary
also estimates false nods per hour *inside windows* at 10 and 30 prompts an hour. The target is at
most 1 false nod per hour inside answer windows.

`log` streams the raw rotation rate and attitude as JSON lines, for example to build the gesture
dataset later:

```sh
./run.sh --output out/session.jsonl log
```

Record the numbers in [`../RESULTS.md`](../RESULTS.md), section 5.
