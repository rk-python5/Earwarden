# Speech (Step 0)

This spike covers the plan's item: run Kokoro and Parakeet through mlx-audio on the M2, measure
time to first audio, and test 100 recorded replies, quiet and noisy. It adds three checks from the
design review:

- **Pronunciation (P-03, P-04):** which words Kokoro can't pronounce without espeak-ng. This runs
  anywhere and is already measured below.
- **Confidence (P-05):** a per-word confidence score from Parakeet, and whether it separates right
  transcripts from wrong ones.
- **No false approvals (P-07, P-08):** whether approval words inside other replies ever approve, and
  whether the plan's sound-alike challenge matching accepts decoys.

Everything except `g2p_coverage.py` needs macOS on Apple Silicon. Each script declares its own
dependencies, which `uv run` installs into its own environment under `.tools/` the first time.
Several hundred MB of models come down from Hugging Face on the first run, into
`.tools/huggingface/`. Run the commands from the repo root, after `source dev/activate`.

## 1. Pronunciation coverage (any OS, already measured)

```sh
uv run spikes/speech/g2p_coverage.py [--words-file names.txt]
```

This was measured on 3 Nov 2026 with misaki 0.9.4 and no espeak-ng fallback. That's the setup
mlx-audio falls back to when espeak-ng is missing, and the only one the plan's licence rule
allows.

- 48 of the 87 identifiers in `speech_data.py` (55%) lose some or all of their audio.
- 476 of the top 1,000 PyPI package names (47.6%) would be silent, including `numpy`, `pydantic`
  and `pytest`.
- One of the already-normalised summaries loses "quickstart".
- Spelled letter by letter, every one of those words comes back.

## 2. Kokoro latency

```sh
uv run spikes/speech/tts_latency.py --save                 # time to first audio, speed, memory
uv run spikes/speech/tts_latency.py --save --no-fallback   # then listen to out/tts/01.wav
```

The script streams sentence by sentence, as the plan specifies. "First audio" is when the first
sentence's samples are ready; Bluetooth output adds its delay on top (`spikes/audio_io` measures
that). The budget is 200 ms.

With `--no-fallback` you can hear section 1's finding: "quickstart" disappears from summary 01.
`misaki[en]` bundles espeak-ng (GPL) for this run only; Earwarden itself must not (P-04).

## 3. Record the replies (about 25 minutes)

Put your AirPods in, then:

```sh
uv run spikes/speech/record_replies.py --condition quiet
uv run spikes/speech/record_replies.py --condition noisy    # kitchen, street, or a TV on
```

Each condition has 50 replies. They cover:

- the plan's answers ("yes", "no", "wait", "no, use poetry instead"), plus a few off-list ones
- approval words inside refusals ("don't do it", "do it later")
- addressing a session ("API, yes") and the push-to-talk commands
- ten challenge phrases ("approve orchard"), plus decoys that must not pass ("approve orchid" when
  Earwarden asked for "orchard")

Read each line naturally. Use `--only id1,id2` to redo some. Recordings stay in `out/replies/`,
which git ignores.

## 4. Parakeet

```sh
uv run spikes/speech/asr_eval.py
```

For each condition, the report gives:

- transcript accuracy and yes/no accuracy (targets: ≥98% quiet, ≥95% noisy)
- **false approvals**, which must be zero
- approvals missed, each of which costs a re-ask

It also gives recognition time and memory for the whole run. For each candidate re-ask threshold
on the confidence score, it prints one line saying what share of wrong transcripts that threshold
would catch and what share of right ones it would needlessly re-ask.

Finally, it shows whether the plan's sound-alike matcher (Double Metaphone with one edit allowed)
accepts the decoys. The intent rules are in `speech_data.py`, and `tests/spikes` checks them
against every label.

Two diagnostics follow the summary:

- **Misheard replies:** every reply whose transcript isn't exactly what was said, with the intent
  it got and its confidence.
- **Two what-if lines for challenge phrases:**
  - Counting "approved" and "a proof" as the word "approve". The first run on the Mac heard both
    in place of "approve".
  - Letting the challenge word alone decide: the last word of a reply of four words or fewer,
    with no negation in it. The Mac runs showed the recogniser rarely hears "approve" itself, but
    usually gets the challenge word right.

```sh
uv run spikes/speech/asr_eval.py --trim
```

`--trim` cuts the silence around each reply before recognition, keeping a quarter of a second
either side, the way the real pipeline's voice detector will. Comparing the two runs shows whether
the fixed 3-second window causes misses, such as a bare "yes" coming back empty.

To compare recognisers on the same recordings, add `--model`:

```sh
uv run spikes/speech/asr_eval.py --trim --model mlx-community/parakeet-tdt-0.6b-v3
uv run spikes/speech/asr_eval.py --trim --model mlx-community/whisper-large-v3-turbo-asr-fp16
```

Whisper runs without the confidence score, because the patched decode only works for TDT models
like Parakeet. Each run writes its own CSV to `out/`, named after the model.

Moonshine is a small, English-only recogniser built for short commands:

```sh
uv run spikes/speech/asr_eval.py --trim --model UsefulSensors/moonshine-base
```

## 5. Two-stage recognition (seconds, no models)

```sh
uv run spikes/speech/combine.py parakeet-tdt-0.6b-v2 whisper-large-v3-turbo-asr-fp16
```

This works out, from two finished runs, what would happen if the first recogniser heard every
reply and the second got a listen only when the first was unclear (an empty transcript included).
Both are judged with Earwarden's rules. For each setup it reports:

- yes/no accuracy
- false approvals
- approvals missed
- how often the second listen was needed
- the time per reply, adding both recognisers when both ran

Any two model names from finished `--trim` runs work.

Write the numbers in [`../RESULTS.md`](../RESULTS.md), section 2.
