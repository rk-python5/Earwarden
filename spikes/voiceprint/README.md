# Voiceprint (Step 0)

This spike covers the plan's item: score 10 of your phrases and 10 of a friend's with ECAPA, and
check the gap. It adds one check the design depends on (D-002): ECAPA exported to ONNX gives the
same embeddings as PyTorch at every phrase length, so the daemon never needs PyTorch.

It runs on any OS with the dependencies, but it was written for the M2. The first run downloads
PyTorch and the ECAPA model from Hugging Face; both stay inside the repo, under `.tools/` and
`out/`. Run the commands from the repo root, after `source dev/activate`.

## 1. Record the phrases

Use the speech spike's recorder, keeping only the ten challenge phrases ("approve orchard" and so
on). Record them through the AirPods mic, in the same headset mode Earwarden will use:

```sh
PHRASES=ch-orchard,ch-lantern,ch-harbor,ch-copper,ch-juniper,ch-ribbon,ch-marble,ch-compass,ch-tunnel,ch-glacier
uv run spikes/speech/record_replies.py --condition you    --only $PHRASES
uv run spikes/speech/record_replies.py --condition friend --only $PHRASES   # your friend speaks
```

Ask your friend first. Their recordings stay on your Mac (git-ignored) and are only used here.

## 2. Score them

```sh
uv run spikes/voiceprint/ecapa_gap.py
uv run spikes/voiceprint/ecapa_gap.py --trim
```

`--trim` first cuts the silence around each phrase, keeping a quarter of a second either side. It
uses the same rule as the speech spike's `--trim`, and it's what Earwarden's voice detector will do.
A phrase lasts about a second of each 3-second recording, so without trimming, the silence and
room noise, the same for both of you, make up most of what's scored.

Your first five phrases, in alphabetical order, build the profile. The other five, and all ten of
your friend's, are scored against it. The report gives:

- every phrase's score, yours and your friend's, where 1.0 means the same voice
- your lowest score and your friend's highest
- **the gap** between them: positive means a clean separation on this small sample
- the gap on the phrases you both said outside the profile only. Your friend also says the five
  phrases that built your profile, and saying the same words can raise a score, so this compares
  like with like.
- a mid-point threshold (Phase 2 calibrates the real one, aiming for at most 2% impostors accepted)
- **ONNX parity:** the lowest cosine similarity between ONNX and PyTorch embeddings. The target is
  at least 0.999. Every recording is 3 seconds long, but Earwarden will trim silence, so phrases
  will vary. Each recording is therefore also cut to 0.5, 1, 1.5, 2 and 2.5 seconds, and all
  lengths must pass.
- the exported model's size, counting its weights. The exporter can put the weights in a
  separate `.onnx.data` file next to the graph.
- how fast and how big an onnxruntime-only process is: the speaker-model share of the memory
  budget, estimated at about 100 MB

The ONNX graph covers the embedding network only. The daemon will also need ECAPA's filterbank
features computed without PyTorch; that's Phase 2.

Record the numbers in [`../RESULTS.md`](../RESULTS.md), section 6.
