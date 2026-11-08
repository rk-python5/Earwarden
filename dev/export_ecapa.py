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
#     "soundfile",
# ]
# ///
"""Export ECAPA for the voiceprint, and check Earshot's numpy features match SpeechBrain's.

    uv run dev/export_ecapa.py [--home .tools/earshot]

It writes `models/ecapa_embedding.onnx` (and its weights file) under Earshot's home, which is what
`earshot enroll` and the daemon load. Then it checks parity on Step 0's recordings, if they're
there, and on synthetic noise:

- Earshot's `voiceprint.fbank` against SpeechBrain's features: the largest difference
- the ONNX model on Earshot's features against PyTorch on SpeechBrain's: the lowest cosine, which
  must be at least 0.999, as Step 0 required of the export
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earshot import paths  # noqa: E402
from earshot.voice import voiceprint  # noqa: E402

RECORDINGS = ROOT / "spikes" / "speech" / "out" / "replies"


def export(model: torch.nn.Module, path: Path) -> None:
    feats = torch.randn(1, 200, voiceprint.N_MELS)
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


def clips() -> list[tuple[str, np.ndarray]]:
    found = [
        (f"{p.parent.name}/{p.name}", soundfile.read(p, dtype="float32")[0])
        for p in sorted(RECORDINGS.glob("*/*.wav"))
    ]
    rng = np.random.default_rng(0)
    found.append(("noise", (rng.standard_normal(24_000) * 0.05).astype(np.float32)))
    t = np.arange(8_000) / voiceprint.RATE
    found.append(("tone", (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", help="Earshot's home, as for earshotd (default: the usual)")
    args = parser.parse_args()
    from speechbrain.inference.speaker import EncoderClassifier

    model_dir = paths.resolve(args.home).models_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(model_dir / "speechbrain"),
        run_opts={"device": "cpu"},  # the exporter traces on the CPU, not Apple's GPU
    )
    classifier.eval()
    onnx_path = model_dir / voiceprint.MODEL
    for old in model_dir.glob(f"{voiceprint.MODEL}*"):
        old.unlink()
    export(classifier.mods.embedding_model, onnx_path)
    shutil.rmtree(model_dir / "speechbrain", ignore_errors=True)
    size = sum(p.stat().st_size for p in model_dir.glob(f"{voiceprint.MODEL}*")) / 1e6
    print(f"Exported {onnx_path} ({size:.1f} MB)")

    embedder = voiceprint.Embedder(onnx_path)
    worst_feature, worst_cosine, worst_name = 0.0, 1.0, ""
    for name, wav in clips():
        with torch.no_grad():
            batch = torch.from_numpy(wav).unsqueeze(0)
            reference = classifier.mods.mean_var_norm(
                classifier.mods.compute_features(batch), torch.ones(1)
            )
            torch_embedding = classifier.mods.embedding_model(reference).squeeze().numpy()
        ours = voiceprint.fbank(wav)
        worst_feature = max(worst_feature, float(np.max(np.abs(ours - reference[0].numpy()))))
        cosine = voiceprint.cosine(embedder.embed(wav), [float(x) for x in torch_embedding])
        if cosine < worst_cosine:
            worst_cosine, worst_name = cosine, name
    print(f"Features, largest difference from SpeechBrain: {worst_feature:.2e}")
    print(f"Embeddings, lowest cosine with PyTorch: {worst_cosine:.6f} ({worst_name})")
    passed = worst_cosine >= 0.999
    print("Parity: pass" if passed else "Parity: FAIL (needs at least 0.999)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
