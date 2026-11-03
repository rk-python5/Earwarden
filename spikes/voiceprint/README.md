# Voiceprint (Step 0)

This spike covers the plan's item: score 10 of your phrases and 10 of a friend's with ECAPA, and
check the gap. It adds one check the design depends on (D-002): ECAPA exported to ONNX gives the
same embeddings as PyTorch at every phrase length, so the daemon never needs PyTorch.

It runs on any OS with the dependencies, but it was written for the M2. The first run downloads
PyTorch and the ECAPA model from Hugging Face. Run the commands from the repo root.

## 1. Record the phrases

Use the speech spike's recorder, keeping only the ten challenge phrases ("approve orchard" and so
on). Record them through the AirPods mic, in the same headset mode Earshot will use:

```sh
PHRASES=ch-orchard,ch-lantern,ch-harbor,ch-copper,ch-juniper,ch-ribbon,ch-marble,ch-compass,ch-tunnel,ch-glacier
uv run spikes/speech/record_replies.py --condition you    --only $PHRASES
uv run spikes/speech/record_replies.py --condition friend --only $PHRASES   # your friend speaks
```

Ask your friend first. Their recordings stay on your Mac (git-ignored) and are only used here.

## 2. Score them

```sh
uv run spikes/voiceprint/ecapa_gap.py
```

Your first five phrases build the profile. The other five, and all ten of your friend's, are
scored against it. The report gives:

- your lowest score and your friend's highest
- **the gap** between them: positive means a clean separation on this small sample
- a mid-point threshold (Phase 2 calibrates the real one, aiming for at most 2% impostors accepted)
- **ONNX parity:** the lowest cosine similarity between ONNX and PyTorch embeddings across every
  recording length. The target is at least 0.999.
- how fast and how big an onnxruntime-only process is: the speaker-model share of the memory
  budget, estimated at about 100 MB

The ONNX graph covers the embedding network only. The daemon will also need ECAPA's filterbank
features computed without PyTorch; that's Phase 2.

Record the numbers in [`../RESULTS.md`](../RESULTS.md), section 6.
