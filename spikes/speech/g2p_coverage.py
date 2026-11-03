# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "misaki==0.9.4",
#     "num2words>=0.5.13",
#     "spacy>=3.8,<3.9",
#     "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
# ]
# ///
"""Which words would Kokoro skip? Runs on any OS; no MLX or audio needed.

Kokoro's English text front-end (misaki) looks words up in its dictionary. With no espeak-ng
fallback, which is the plan's licence-safe setup, mlx-audio drops any word that gets no phonemes,
silently (decisions.md, P-03 and P-04). This script runs the identifiers and spoken summaries from
speech_data.py, plus an optional word list, through misaki exactly that way. It reports which
words would vanish from the audio, and whether spelling them letter by letter rescues them.

    uv run spikes/speech/g2p_coverage.py
    uv run spikes/speech/g2p_coverage.py --words-file names.txt   # one word per line
"""

from __future__ import annotations

import argparse
from pathlib import Path

from misaki import en
from speech_data import IDENTIFIERS, SUMMARIES


def silent_tokens(g2p: en.G2P, text: str) -> list[str]:
    """Tokens with letters or digits that come out of the front-end without phonemes."""
    _, tokens = g2p(text)
    return [t.text for t in tokens if any(c.isalnum() for c in t.text) and not t.phonemes]


def spelled(word: str) -> str:
    return " ".join(c.upper() for c in word if c.isalnum())


def check(g2p: en.G2P, words: list[str], label: str, show: int) -> None:
    dropped = {w: silent_tokens(g2p, w) for w in words}
    dropped = {w: parts for w, parts in dropped.items() if parts}
    rescued = [w for w in dropped if not silent_tokens(g2p, spelled(w))]
    share = len(dropped) / len(words) if words else 0.0
    print(
        f"\n{label}: {len(dropped)} of {len(words)} ({share:.1%}) lose some or all of their audio"
    )
    for word, parts in list(dropped.items())[:show]:
        print(f"  {word!r:44} silent: {', '.join(parts)}")
    if len(dropped) > show:
        print(f"  … and {len(dropped) - show} more")
    print(f"  Spelled letter by letter, {len(rescued)} of {len(dropped)} come back fully.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words-file", type=Path, help="extra words, one per line")
    parser.add_argument("--show", type=int, default=60, help="how many dropped words to list")
    args = parser.parse_args()

    # The same settings mlx-audio 0.6.4 uses when espeak-ng is missing: no fallback, unk="".
    g2p = en.G2P(trf=False, british=False, fallback=None, unk="")

    check(g2p, IDENTIFIERS, "Identifiers from speech_data.py", args.show)

    print("\nSpoken summaries (already normalised):")
    for summary in SUMMARIES:
        silent = silent_tokens(g2p, summary)
        print(
            f"  {'OK  ' if not silent else 'DROP'} {summary[:70]}"
            + (f"  → {silent}" if silent else "")
        )

    if args.words_file:
        lines = args.words_file.read_text(encoding="utf-8").splitlines()
        words = [w.strip() for w in lines if w.strip()]
        check(g2p, words, f"Words from {args.words_file.name}", args.show)


if __name__ == "__main__":
    main()
