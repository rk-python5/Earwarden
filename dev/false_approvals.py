"""Can noise, or a reply that began before the window, be heard as an approval? (P-20)

The recorded-audio check, run by hand on the Mac (D-023). It sends Step 0's AirPods recordings
of rehaan through the daemon's own listening path: the endpointer, Silero VAD, Parakeet (and
Whisper when unclear) and the intent rules. After `uv sync --group voice`:

    uv run python dev/false_approvals.py [spikes/speech/out/replies]

- Whole replies: the window opens before each one, so it must be heard as labelled.
- Room sound: the room before and after each reply, as if a noise had set the endpointer off.
- Cut-off replies: the window opens 50 ms, 100 ms, ... into each non-approval.

The target is zero false approvals, with every real approval still heard. It takes a few minutes.

With `--challenges`, it checks tier 2's challenge words instead (milestone 5): each recorded
"approve <word>" must match its word, and the decoys ("approve orchid" for orchard), a wrong word
and a bare "yes" must not. It takes about a minute.
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

from earwarden.voice import challenge, endpoint, intents
from earwarden.voice.mac import ASR_RATE, FRAME_S, PRE_ROLL_S, MacVoice

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
    window = opened  # the search moves past noises; the window itself doesn't
    while True:
        reply = endpoint.find_reply(levels, opened, now, window)
        if reply is None:
            return "nothing", ""
        end = now if reply.end is None else reply.end
        candidate = clip(audio, max(opened, reply.start - PRE_ROLL_S), end + FRAME_S + 0.25)
        if voice.is_speech(candidate):
            if reply.cut_off:  # never parsed (P-20)
                return "cut off", ""
            transcript = voice._recognize(candidate).transcript
            return intents.parse(transcript).kind, transcript
        opened = end + FRAME_S  # noise: listen on after it, as the daemon does


def challenges(voice: MacVoice, replies: Path, rows: list[dict[str, str]]) -> int:
    """Tier 2: genuine challenge replies must match their word; decoys and wrong words mustn't."""
    accepted = genuine = refused = trick = 0
    for row in rows:
        if not row["challenge"] or row["condition"] == "friend":
            continue
        transcript = hear(voice, read(replies / row["file"]), 0.0)[1]
        match = challenge.matches(transcript, row["challenge"])
        name = f"{row['condition']}/{row['id']} {row['text']!r} for {row['challenge']}"
        if row["intent"] == "approve":
            genuine += 1
            accepted += match
            if not match:
                print(f"NOT ACCEPTED {name}: heard {transcript!r}")
        else:
            trick += 1
            refused += not match
            if match:
                print(f"FALSE MATCH {name}: heard {transcript!r}")
    print(f"\ngenuine challenge replies accepted: {accepted} of {genuine}")
    print(f"decoys, wrong words and bare yeses refused: {refused} of {trick}")
    return 1 if refused < trick else 0


def main() -> int:
    replies = Path(
        next((a for a in sys.argv[1:] if not a.startswith("-")), "spikes/speech/out/replies")
    )
    with (replies / "labels.csv").open(encoding="utf-8") as labels:
        rows = [row for row in csv.DictReader(labels) if row["condition"] != "friend"]
    voice = MacVoice()
    voice.load()
    if "--challenges" in sys.argv:
        return challenges(voice, replies, rows)
    false: list[str] = []
    wrong: list[str] = []
    yes_no: dict[str, list[bool]] = {}  # the spec's yes/no accuracy, per room
    approvals = approvals_heard = rooms = rooms_speech = cuts = cuts_flagged = 0
    vad_ms: list[float] = []
    for row in rows:
        audio = read(replies / row["file"])
        name = f"{row['condition']}/{row['id']} {row['text']!r}"
        expected = intents.parse(row["text"]).kind
        kind, transcript = hear(voice, audio, 0.0)
        if kind != expected:
            wrong.append(f"{name}: expected {expected}, heard {kind} {transcript!r}")
        if expected in ("approve", "deny"):
            yes_no.setdefault(row["condition"], []).append(kind == expected)
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
    for room, results in sorted(yes_no.items()):
        target = {"quiet": "98%", "noisy": "95%"}.get(room, "")
        print(
            f"yes/no in the {room} recordings: {sum(results)} of {len(results)} "
            f"({sum(results) / len(results):.1%})" + (f"; the target is {target}" if target else "")
        )
    print(f"Silero VAD:      median {statistics.median(vad_ms):.0f} ms per clip")
    return 1 if false or approvals_heard < approvals else 0


if __name__ == "__main__":
    sys.exit(main())
