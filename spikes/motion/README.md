# Head motion (Step 0)

This spike covers the plan's item: prototype `CMHeadphoneMotionManager` in Swift and count false
nods over an hour of normal work. It's a small command-line tool that reads your AirPods' head
motion and runs the plan's v1 detector: two rotation-rate swings of opposite sign within 1.2 s
make a nod (pitch) or a shake (yaw).

You need macOS 14 or later, Xcode 15 or later, and AirPods with head tracking (AirPods Pro, Max,
or third generation and later) connected to the Mac. CI builds the tool on every push, so you know
it compiles.

```sh
cd spikes/motion
swift build -c release
.build/release/motion-spike calibrate
```

The first run should make macOS ask for motion access. Note the name the prompt shows; the
executable carries its own usage text. If it says "denied", allow it in System Settings → Privacy &
Security → Motion & Fitness.

## 1. Calibrate (1 minute)

`calibrate` asks you to nod five times, then shake your head five times. It reports which
rotation axis carries each gesture. If they aren't `x` for nods and `z` for shakes, pass
`--pitch-axis` and `--yaw-axis` to the other commands. Then try some deliberate nods and shakes:

```sh
.build/release/motion-spike count --minutes 2      # nod and shake a few times; all detected?
```

If small nods are missed, lower `--threshold` (rad/s, default 1.0). If one swing counts twice,
raise it.

## 2. False nods over an hour of normal work

```sh
.build/release/motion-spike count --minutes 60
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
.build/release/motion-spike log > out/session.jsonl
```

Record the numbers in [`../RESULTS.md`](../RESULTS.md), section 5.
