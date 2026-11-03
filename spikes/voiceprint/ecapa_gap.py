# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "speechbrain==1.1.2",
#     "torch==2.11.*",
#     "torchaudio==2.11.*",
#     "onnx>=1.23",
#     "onnxscript",
#     "onnxruntime>=1.29",
#     "numpy",
#     "scipy",
#     "soundfile",
# ]
# ///
"""ECAPA voiceprint: is there a clear gap between your phrases and a friend's? Does ONNX match?

    uv run spikes/voiceprint/ecapa_gap.py
    uv run spikes/voiceprint/ecapa_gap.py --you DIR --friend DIR --enroll 5

By default it reads the challenge phrases recorded with the speech spike:
spikes/speech/out/replies/you/ and spikes/speech/out/replies/friend/ (see README.md).
Your first `--enroll` phrases build the profile; the rest of yours, and all of your friend's,
are scored against it by cosine similarity.

It then exports ECAPA's embedding network to ONNX and checks that onnxruntime gives the same
embeddings as PyTorch on every recording, at every length. The plan keeps PyTorch out of the
daemon (D-002), so this must hold. It also measures embedding time and the memory of an
onnxruntime-only process. Runs on any OS; this script was written for the M2.
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import subprocess
import sys
import time
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
REPLIES = HERE.parent / "speech" / "out" / "replies"
RATE = 16_000


def rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3  # bytes on macOS, KiB on Linux


def ort_child(model: str, features: str) -> None:
    """Runs in a separate process: onnxruntime only, as the daemon would be."""
    before = rss_mb()
    import onnxruntime as ort

    session = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    feats = np.load(features)
    name = session.get_inputs()[0].name
    session.run(None, {name: feats})
    times = []
    for _ in range(20):
        start = time.perf_counter()
        session.run(None, {name: feats})
        times.append((time.perf_counter() - start) * 1000)
    print(
        json.dumps(
            {
                "rss_before_mb": before,
                "rss_after_mb": rss_mb(),
                "median_ms": statistics.median(times),
            }
        )
    )


def load_wav(path: Path) -> np.ndarray:
    import soundfile as sf
    from scipy.signal import resample_poly

    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if rate != RATE:
        g = gcd(rate, RATE)
        mono = resample_poly(mono, RATE // g, rate // g).astype(np.float32)
    return mono


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def export_onnx(model: Any, feats: Any, path: Path) -> str:
    """Try the current exporter with a dynamic time axis, then the legacy one. Returns which."""
    import torch

    errors = []
    try:
        frames = torch.export.Dim("frames", min=10, max=6000)
        torch.onnx.export(
            model,
            (feats,),
            str(path),
            dynamo=True,
            input_names=["feats"],
            output_names=["embedding"],
            dynamic_shapes={"x": {1: frames}},
        )
        return "dynamo"
    except Exception as exc:
        errors.append(f"dynamo: {exc!r}"[:300])
    try:
        torch.onnx.export(
            model,
            (feats,),
            str(path),
            dynamo=False,
            opset_version=17,
            input_names=["feats"],
            output_names=["embedding"],
            dynamic_axes={"feats": {1: "frames"}},
        )
        return "legacy"
    except Exception as exc:
        errors.append(f"legacy: {exc!r}"[:300])
    raise RuntimeError("ONNX export failed:\n  " + "\n  ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--you", type=Path, default=REPLIES / "you")
    parser.add_argument("--friend", type=Path, default=REPLIES / "friend")
    parser.add_argument("--enroll", type=int, default=5, help="your phrases used for the profile")
    parser.add_argument("--ort-child", nargs=2, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.ort_child:
        ort_child(*args.ort_child)
        return

    yours = sorted(args.you.glob("*.wav"))
    theirs = sorted(args.friend.glob("*.wav"))
    if len(yours) <= args.enroll or not theirs:
        sys.exit(f"Need more than {args.enroll} WAVs in {args.you} and some in {args.friend}.")

    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    start = time.perf_counter()
    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(OUT / "model"),
        run_opts={"device": "cpu"},
    )
    classifier.eval()
    print(f"Model loaded in {time.perf_counter() - start:.1f} s")

    def features(wav: np.ndarray) -> Any:
        batch = torch.from_numpy(wav).unsqueeze(0)
        with torch.no_grad():
            feats = classifier.mods.compute_features(batch)
            return classifier.mods.mean_var_norm(feats, torch.ones(1))

    def torch_embedding(feats: Any) -> np.ndarray:
        with torch.no_grad():
            return classifier.mods.embedding_model(feats).squeeze().numpy()

    clips = {path: load_wav(path) for path in yours + theirs}
    feats = {path: features(wav) for path, wav in clips.items()}
    timings = []
    embeddings = {}
    for path, f in feats.items():
        begin = time.perf_counter()
        embeddings[path] = torch_embedding(f)
        timings.append((time.perf_counter() - begin) * 1000)

    profile = unit(np.mean([unit(embeddings[p]) for p in yours[: args.enroll]], axis=0))
    genuine = [float(unit(embeddings[p]) @ profile) for p in yours[args.enroll :]]
    impostor = [float(unit(embeddings[p]) @ profile) for p in theirs]
    gap = min(genuine) - max(impostor)
    print(
        f"\nProfile from {args.enroll} of your phrases; scored {len(genuine)} more of yours "
        f"and {len(impostor)} of your friend's."
    )
    print(f"  yours:    min {min(genuine):.3f}  median {statistics.median(genuine):.3f}")
    print(f"  friend's: max {max(impostor):.3f}  median {statistics.median(impostor):.3f}")
    print(
        f"  gap (your lowest minus their highest): {gap:+.3f}  "
        f"{'clear separation' if gap > 0 else 'OVERLAP: some phrases cannot be told apart'}"
    )
    middle = (min(genuine) + max(impostor)) / 2
    print(f"  a threshold of {middle:.3f} would sit in the middle (Phase 2 calibrates it properly)")
    print(f"  PyTorch embedding time: median {statistics.median(timings):.0f} ms per phrase")

    OUT.mkdir(parents=True, exist_ok=True)
    onnx_path = OUT / "ecapa_embedding.onnx"
    sample = feats[yours[args.enroll]]
    exporter = export_onnx(classifier.mods.embedding_model, sample, onnx_path)
    import onnxruntime as ort

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    cosines, diffs = [], []
    for path, f in feats.items():
        onnx_emb = session.run(None, {name: f.numpy()})[0].squeeze()
        cosines.append(float(unit(onnx_emb) @ unit(embeddings[path])))
        diffs.append(float(np.max(np.abs(onnx_emb - embeddings[path]))))
    lengths = sorted({f.shape[1] for f in feats.values()})
    print(
        f"\nONNX export ({exporter} exporter) checked on {len(cosines)} recordings, "
        f"{lengths[0]} to {lengths[-1]} frames:"
    )
    print(f"  cosine to PyTorch: min {min(cosines):.6f}   (target ≥ 0.999)")
    print(f"  largest element difference: {max(diffs):.2e}")
    print(f"  file size: {onnx_path.stat().st_size / 1e6:.1f} MB")

    np.save(OUT / "sample_feats.npy", sample.numpy())
    child = subprocess.run(
        [sys.executable, __file__, "--ort-child", str(onnx_path), str(OUT / "sample_feats.npy")],
        capture_output=True,
        text=True,
        check=True,
    )
    stats = json.loads(child.stdout.strip().splitlines()[-1])
    print(
        f"  onnxruntime-only process: {stats['median_ms']:.0f} ms per embedding, "
        f"peak memory {stats['rss_after_mb']:.0f} MB "
        f"(Python and numpy alone: {stats['rss_before_mb']:.0f} MB; budget about 100 MB)"
    )
    print(
        "\nNote: the daemon also needs ECAPA's filterbank features without PyTorch; that's "
        "Phase 2 work and isn't covered here."
    )


if __name__ == "__main__":
    main()
