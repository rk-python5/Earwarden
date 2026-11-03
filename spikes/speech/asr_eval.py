# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["mlx-audio==0.6.4", "metaphone==0.6", "numpy"]
# ///
"""Parakeet on the recorded replies. macOS on Apple Silicon only.

    uv run spikes/speech/asr_eval.py
    uv run spikes/speech/asr_eval.py --model mlx-community/parakeet-tdt-0.6b-v2

The report covers:

- Transcript accuracy and yes/no accuracy, by condition.
- False approvals: these must be zero.
- Recognition time and memory.
- Whether a per-word confidence score separates right from wrong transcripts.

mlx-audio's decoder keeps no probabilities, so this script re-runs the same greedy decode while
keeping the softmax probability of every token it picks (decisions.md, P-05). It also checks
whether the plan's sound-alike challenge matching (Double Metaphone with a one-edit allowance)
would accept the decoy replies (P-08). Reads out/replies/labels.csv from record_replies.py and
writes out/asr_results.csv.
"""

from __future__ import annotations

import argparse
import csv
import platform
import resource
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from speech_data import intent, normalize

HERE = Path(__file__).resolve().parent
REPLIES = HERE / "out" / "replies"
RESULTS = HERE / "out" / "asr_results.csv"
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95)


def levenshtein(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, start=1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def plan_challenge_match(transcript: str, challenge: str) -> bool:
    """The plan's matcher: 'approve <word>' with the word within one Double Metaphone edit."""
    from metaphone import doublemetaphone

    words = normalize(transcript).split()
    if len(words) != 2 or words[0] != "approve":
        return False
    heard = [c for c in doublemetaphone(words[1]) if c]
    wanted = [c for c in doublemetaphone(challenge) if c]
    return min(levenshtein(x, y) for x in heard for y in wanted) <= 1


def decode_with_confidence(model: Any, path: Path) -> tuple[str, list[float]]:
    """mlx-audio 0.6.4's ParakeetTDT.decode for one file, keeping each chosen token's probability.

    Returns the text and one confidence per word (the lowest token probability in the word).
    """
    import mlx.core as mx
    from mlx_audio.stt.models.parakeet import parakeet as pk
    from mlx_audio.stt.utils import load_audio

    audio = load_audio(str(path), sr=model.preprocessor_config.sample_rate, dtype=mx.bfloat16)
    mel = model._log_mel_spectrogram(audio)
    if mel.ndim == 2:
        mel = mx.expand_dims(mel, 0)
    features, lengths = model.encoder(mel)
    mx.eval(features, lengths)
    features = features[0:1]
    blank = model.blank_id
    hidden, cell = model._make_initial_decoder_state(1, features.dtype)
    last, t, new_symbols = blank, 0, 0
    pieces: list[tuple[str, float]] = []
    while t < int(lengths[0]):
        feature = features[:, t : t + 1]
        current = mx.array([[last]], dtype=mx.int32)
        embedded = model.decoder.prediction["embed"](current)
        embedded = mx.where(
            mx.expand_dims(current == blank, axis=-1), mx.zeros_like(embedded), embedded
        )
        out, (h, c) = model.decoder.prediction["dec_rnn"](embedded, (hidden, cell))
        joint = model.joint(feature, out.astype(feature.dtype))
        logits = joint[0, 0, :, : blank + 1].astype(mx.float32)
        token = mx.argmax(logits)
        prob = mx.max(mx.softmax(logits, axis=-1))
        decision = mx.argmax(joint[0, 0, :, blank + 1 :])
        mx.eval(token, prob, decision, h, c)
        token_i, duration = int(token), model.durations[int(decision)]
        if token_i != blank:
            last = token_i
            hidden, cell = h.astype(feature.dtype), c.astype(feature.dtype)
            if not pk.tokenizer.is_special_token(token_i, model.vocabulary):
                pieces.append((pk.tokenizer.decode([token_i], model.vocabulary), float(prob)))
        t += duration
        new_symbols += 1
        if duration != 0:
            new_symbols = 0
        elif model.max_symbols is not None and model.max_symbols <= new_symbols:
            t, new_symbols = t + 1, 0

    text = "".join(piece for piece, _ in pieces).strip()
    words: list[float] = []
    for piece, prob in pieces:
        if piece.startswith(" ") or not words:
            words.append(prob)
        else:
            words[-1] = min(words[-1], prob)
    return text, words


def pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.1%})" if whole else "—"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="mlx-community/parakeet-tdt-0.6b-v2")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        sys.exit("MLX needs macOS on Apple Silicon.")
    labels_path = REPLIES / "labels.csv"
    if not labels_path.exists():
        sys.exit(f"No {labels_path}; record replies first (record_replies.py).")

    import mlx.core as mx
    from mlx_audio.stt.utils import load as load_stt

    start = time.perf_counter()
    model = load_stt(args.model)
    load_s = time.perf_counter() - start
    if not hasattr(model, "durations"):
        sys.exit(f"{args.model} isn't a TDT model; the confidence decode needs one.")
    with labels_path.open(newline="", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    model.generate(str(REPLIES / labels[0]["file"]))  # warm-up

    rows = []
    for label in labels:
        path = REPLIES / label["file"]
        start = time.perf_counter()
        stock_text = model.generate(str(path)).text
        latency_ms = (time.perf_counter() - start) * 1000
        text, word_conf = decode_with_confidence(model, path)
        challenge = label["challenge"] or None
        got = intent(text, challenge)
        rows.append(
            {
                **label,
                "transcript": text,
                "stock_transcript": stock_text,
                "exact": normalize(text) == normalize(label["text"]),
                "got_intent": got,
                "false_approval": got == "approve" and label["intent"] != "approve",
                "min_conf": min(word_conf, default=0.0),
                "mean_conf": statistics.fmean(word_conf) if word_conf else 0.0,
                "latency_ms": latency_ms,
                "plan_match_accepts": (plan_challenge_match(text, challenge) if challenge else ""),
            }
        )

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} replies, model {args.model} (loaded in {load_s:.1f} s)\n")
    for condition in sorted({r["condition"] for r in rows}):
        group = [r for r in rows if r["condition"] == condition]
        yes_no = [r for r in group if r["intent"] in {"approve", "deny"} and not r["challenge"]]
        print(f"{condition}:")
        exact = sum(r["exact"] for r in group)
        correct = sum(r["got_intent"] == r["intent"] for r in group)
        yes_no_correct = sum(r["got_intent"] == r["intent"] for r in yes_no)
        print(f"  transcript exact     {pct(exact, len(group))}")
        print(f"  intent correct       {pct(correct, len(group))}")
        print(
            f"  yes/no correct       {pct(yes_no_correct, len(yes_no))}"
            "   (target ≥98% quiet, ≥95% noisy)"
        )
        print(f"  FALSE APPROVALS      {sum(r['false_approval'] for r in group)}   (must be 0)")
        missed = [r for r in group if r["intent"] == "approve" and r["got_intent"] != "approve"]
        print(f"  approvals missed     {len(missed)}   (each costs a re-ask)")

    latencies = [r["latency_ms"] for r in rows]
    print(
        f"\nRecognition time: median {statistics.median(latencies):.0f} ms, "
        f"max {max(latencies):.0f} ms per reply"
    )
    print(
        f"Peak MLX memory {mx.get_peak_memory() / 1e9:.2f} GB, "
        f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9:.2f} GB"
    )

    right = [r for r in rows if r["exact"]]
    wrong = [r for r in rows if not r["exact"]]
    print(f"\nConfidence (lowest word probability): {len(right)} right, {len(wrong)} wrong")
    if right and wrong:
        print(
            f"  median when right {statistics.median(r['min_conf'] for r in right):.3f}, "
            f"when wrong {statistics.median(r['min_conf'] for r in wrong):.3f}"
        )
        for threshold in THRESHOLDS:
            caught = sum(r["min_conf"] < threshold for r in wrong)
            reasked = sum(r["min_conf"] < threshold for r in right)
            print(
                f"  re-ask below {threshold:.2f}: catches {pct(caught, len(wrong))} of wrong, "
                f"re-asks {pct(reasked, len(right))} of right"
            )

    decoys = [r for r in rows if r["challenge"] and r["intent"] != "approve"]
    if decoys:
        print("\nChallenge decoys (must not approve):")
        for r in decoys:
            print(
                f"  {r['condition']:6} {r['text']!r:24} heard {r['transcript']!r:24} "
                f"strict: {r['got_intent']:8} plan's matcher accepts: {r['plan_match_accepts']}"
            )
    mismatched = sum(normalize(r["transcript"]) != normalize(r["stock_transcript"]) for r in rows)
    if mismatched:
        print(
            f"\nNote: the confidence decode differs from mlx-audio's own on {mismatched} replies."
        )
    print(f"\nPer-reply results: {RESULTS}")


if __name__ == "__main__":
    main()
