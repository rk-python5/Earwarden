# Attribution

Earwarden is Apache-2.0. These are the models and libraries it uses, and what each asks of you.

## Models

| Model | Used for | License |
| --- | --- | --- |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), MLX build by `mlx-community` | Speaking | Apache-2.0 |
| [Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (NVIDIA), MLX build | Recognising your answer | CC-BY-4.0 |
| [Whisper large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) (OpenAI), MLX build | A second listen when the first is unclear | MIT |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Hearing speech, not noise | MIT |
| [ECAPA-TDNN speaker embeddings](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) (SpeechBrain), exported to ONNX | Checking who is answering | Apache-2.0 |

The ECAPA model was trained on VoxCeleb, whose own terms are for research use. Earwarden ships the
network exported to ONNX and trains nothing; if that matters for how you use Earwarden, read
VoxCeleb's terms.

## Libraries

[mlx](https://github.com/ml-explore/mlx) and [mlx-audio](https://github.com/Blaizzy/mlx-audio)
(MIT), [misaki](https://github.com/hexgrad/misaki) (Apache-2.0),
[spaCy](https://spacy.io) and its `en_core_web_sm` model (MIT),
[num2words](https://github.com/savoirfairelinux/num2words) (LGPL-2.1: used as an ordinary
library, unmodified), [ONNX Runtime](https://onnxruntime.ai) (MIT),
[sounddevice](https://python-sounddevice.readthedocs.io) (MIT), [NumPy](https://numpy.org) (BSD),
[Pydantic](https://pydantic.dev) (MIT), [PyYAML](https://pyyaml.org) (MIT), metaphone (BSD).

**espeak-ng and `phonemizer`, which are GPL, are not installed or used.** Kokoro's pipeline
imports them whether or not it needs them, so Earwarden gives it a stand-in that never starts
(decisions.md, D-022). A word the speech front-end can't pronounce is spelled out instead.

The popular-package lists behind the lookalike check come from
[hugovk's top PyPI packages](https://hugovk.dev/top-pypi-packages/) (names only) and
[npm-high-impact](https://github.com/wooorm/npm-high-impact) (MIT).
