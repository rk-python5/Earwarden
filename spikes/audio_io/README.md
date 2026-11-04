# AirPods audio I/O (Step 0)

This spike covers the plan's item: measure the AirPods mic switch delay and how much playback
leaks into the mic. It adds the self-approval check from the design review (P-06): can a prompt
that ends in "say: approve orchard" be heard by the mic and transcribed as the answer?

You need macOS with AirPods connected as both input and output. Use your normal listening volume.
Run the commands from the repo root, after `source dev/activate`. The first run installs the
dependencies inside the repo; `selfcheck --asr` also downloads Parakeet if the speech spike hasn't
already.

```sh
uv run spikes/audio_io/airpods_io.py devices     # check the AirPods appear as input and output
```

## 1. Mic switch delay (Q-2)

```sh
uv run spikes/audio_io/airpods_io.py switch --trials 5
```

Each trial:

1. Plays a quiet tone in high-quality mode.
2. Opens the AirPods mic, as Earshot does when an answer window opens.
3. Measures how long until the mic delivers live audio. Before then it may deliver silence.

It also counts glitches in the output stream. Listen for the tone dropping or changing quality
when the mic opens. That's the Bluetooth switch to headset mode the plan warns about.

**What it decides:** if the switch takes more than a few hundred milliseconds, keep the mic warm
while any approval is pending, as the plan suggests.

## 2. Playback leak

```sh
uv run spikes/audio_io/airpods_io.py leak        # stay quiet for about 8 seconds
```

This plays a 3-second sweep through the AirPods while recording their mic, and reports:

- **Output-to-mic delay:** Bluetooth out, through the air, and Bluetooth in. Only trust it when the
  correlation is clearly positive.
- **Leak gain:** how much of the playback reaches the mic.
- **Leak above the noise floor:** how audible that leak is.

**What it decides:** if the leak is clearly above the floor, barge-in (talking over Earshot) needs
half-duplex or echo cancellation, and the answer window must wait out the delay.

## 3. Self-approval (P-06)

```sh
uv run spikes/audio_io/airpods_io.py selfcheck --asr    # stay quiet
```

This keeps the mic warm, as Earshot does while an approval is pending, then plays two prompts
through the AirPods with macOS `say`:

- a tier-2 prompt ending "say: approve orchard"
- a tier-1 prompt ending "Nod or say yes"

For each prompt it cuts answer windows starting 0, 100, 250 and 500 ms after playback ends on the
Mac's side, with and without the plan's 1.5 s pre-roll. For each window it reports the level
relative to the room and what Parakeet hears. Any window that the intent rules read as an approval
fails: Earshot would have approved itself.

**What it decides:** the guard delay before an answer window opens, and whether pre-roll may reach
back before the window.

Record the numbers in [`../RESULTS.md`](../RESULTS.md), section 3.
