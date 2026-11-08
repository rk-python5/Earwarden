"""Can noise, or a reply that began before the window, be heard as an approval? (P-20)

The recorded-audio check, run by hand on the Mac (D-023). It sends Step 0's AirPods recordings
of rehaan through the daemon's own listening path: the endpointer, Silero VAD, Parakeet (and
Whisper when unclear) and the intent rules. After `uv sync --group voice`:

    uv run python dev/false_approvals.py [spikes/speech/out/replies]

- Whole replies: the window opens before each one, so it must be heard as labelled.
- Room sound: the room before and after each reply, as if a noise had set the endpointer off.
- Cut-off replies: the window opens 50 ms, 100 ms, ... into each non-approval.

The target is zero false approvals, with every real approval still heard. It takes a few minutes.
"""

from __future__ import annotations

import csv
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from earshot.voice import endpoint, intents
from earshot.voice.mac import ASR_RATE, FRAME_S, PRE_ROLL_S, MacVoice

FRAME = int(FRAME_S * ASR_RATE)
CUT_STEP_S = 0.05


def read(path: Path) -> Any:
    with wave.open(str(path)) as recording:
        raw = recording.readframes(recording.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def frame_levels(audio: Any) -> list[tuple[float, float]]:
    return [
        (i / ASR_RATE, float(np.sqrt(np.mean(audio[i : i + FRAME] ** 2))))
        for i in range(0, len(audio) - FRAME + 1, FRAME)
    ]


def clip(audio: Any, start: float, end: float) -> Any:
    return audio[max(0, int(start * ASR_RATE)) : max(0, int(end * ASR_RATE))]


def hear(voice: MacVoice, audio: Any, opened: float) -> tuple[str, str]:
    """What the daemon makes of this audio if the window opens at `opened` seconds."""
    levels = frame_levels(audio)
    now = len(audio) / ASR_RATE
    while True:
        reply = endpoint.find_reply(levels, opened, now)
        if reply is None:
            return "nothing", ""
        if reply.cut_off:
            return "cut off", ""
        end = now if reply.end is None else reply.end
        candidate = clip(audio, max(opened, reply.start - PRE_ROLL_S), end + FRAME_S + 0.25)
        if voice.is_speech(candidate):
            transcript = voice._recognize(candidate).transcript
            return intents.parse(transcript).kind, transcript
        opened = end + FRAME_S  # noise: listen on after it, as the daemon does


def main() -> int:
    replies = Path(sys.argv[1] if len(sys.argv) > 1 else "spikes/speech/out/replies")
    with (replies / "labels.csv").open(encoding="utf-8") as labels:
        rows = [row for row in csv.DictReader(labels) if row["condition"] != "friend"]
    voice = MacVoice()
    voice.load()
    false: list[str] = []
    wrong: list[str] = []
    approvals = approvals_heard = rooms = rooms_speech = cuts = cuts_flagged = 0
    vad_ms: list[float] = []
    for row in rows:
        audio = read(replies / row["file"])
        name = f"{row['condition']}/{row['id']} {row['text']!r}"
        expected = intents.parse(row["text"]).kind
        kind, transcript = hear(voice, audio, 0.0)
        if kind != expected:
            wrong.append(f"{name}: expected {expected}, heard {kind} {transcript!r}")
        if expected == "approve":
            approvals += 1
            approvals_heard += kind == "approve"
        elif kind == "approve":
            false.append(f"whole {name}: {transcript!r}")

        # The whole utterance, from its first loud frame to its last, pauses and all.
        levels = frame_levels(audio)
        reply = endpoint.find_reply(levels, 0.0, len(audio) / ASR_RATE)
        if reply is None:
            continue
        loud = [t for t, level in levels if level > reply.threshold]
        start, end = loud[0], loud[-1] + FRAME_S
        for tone in (clip(audio, 0, start - 0.3), clip(audio, end + 0.3, len(audio) / ASR_RATE)):
            if len(tone) < 0.4 * ASR_RATE:
                continue
            rooms += 1
            began = time.monotonic()
            speech = voice.is_speech(tone)
            vad_ms.append((time.monotonic() - began) * 1000)
            if speech:
                rooms_speech += 1
                transcript = voice._recognize(tone).transcript
                if intents.parse(transcript).kind == "approve":
                    false.append(f"room {name}: {transcript!r}")
        if expected == "approve":
            continue
        for opened in np.arange(start + CUT_STEP_S, end, CUT_STEP_S):
            cuts += 1
            kind, transcript = hear(voice, audio, float(opened))
            cuts_flagged += kind == "cut off"
            if kind == "approve":
                false.append(f"cut {name} at +{(opened - start) * 1000:.0f} ms: {transcript!r}")

    for line in wrong:
        print(f"MISHEARD {line}")
    for line in false:
        print(f"FALSE APPROVAL {line}")
    print(f"\nwhole replies:   {len(rows) - len(wrong)} of {len(rows)} heard as labelled")
    print(f"real approvals:  {approvals_heard} of {approvals} heard")
    print(f"room sound:      {rooms_speech} of {rooms} clips passed VAD")
    print(f"cut-off replies: {cuts_flagged} of {cuts} windows flagged as cut off")
    print(f"false approvals: {len(false)}")
    print(f"Silero VAD:      median {statistics.median(vad_ms):.0f} ms per clip")
    return 1 if false or approvals_heard < approvals else 0


if __name__ == "__main__":
    sys.exit(main())
