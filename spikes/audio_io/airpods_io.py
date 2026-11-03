# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["numpy", "scipy", "sounddevice>=0.5", "mlx-audio==0.6.4"]
# ///
"""AirPods audio I/O on the Mac: mic switch delay, playback leak, and self-approval. macOS only.

    uv run spikes/audio_io/airpods_io.py devices
    uv run spikes/audio_io/airpods_io.py switch            # how long the mic takes to come alive
    uv run spikes/audio_io/airpods_io.py leak              # how much playback the mic hears
    uv run spikes/audio_io/airpods_io.py selfcheck --asr   # can Earshot hear itself approve? (P-06)

Stay quiet during leak and selfcheck: the mic must hear only the AirPods themselves. Use your
normal listening volume. Raw audio goes to out/ (git-ignored).
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import wave
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
sys.path.insert(0, str(HERE.parent / "speech"))

from speech_data import intent  # noqa: E402

PROMPTS = {
    "tier2": (
        "API wants to push feature slash login to origin. To push, say: approve orchard.",
        "orchard",
    ),
    "tier1": ("Docs wants to edit quickstart dot m d. Nod or say yes.", None),
}
PRE_ROLL_S = 1.5
WINDOW_S = 2.5


def find_device(name: str, kind: str) -> int:
    import sounddevice as sd

    devices: Any = sd.query_devices()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for index, device in enumerate(devices):
        if name.lower() in device["name"].lower() and device[key] > 0:
            return index
    sys.exit(f"No {kind} device matching {name!r}; run the devices command.")


def rate_of(device: int) -> int:
    import sounddevice as sd

    info: Any = sd.query_devices(device)
    return int(info["default_samplerate"])


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return audio
    from scipy.signal import resample_poly

    g = gcd(src, dst)
    return np.asarray(resample_poly(audio, dst // g, src // g), dtype=np.float32)


def db(x: float) -> float:
    return 20 * np.log10(max(x, 1e-12))


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


class Capture:
    """One running input stream. Keeps every block with the monotonic time it arrived."""

    def __init__(self, device: int, rate: int) -> None:
        import sounddevice as sd

        self.rate = rate
        self.blocks: list[tuple[float, np.ndarray]] = []
        self.lock = threading.Lock()

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            arrived = time.monotonic()
            with self.lock:
                self.blocks.append((arrived, indata[:, 0].copy()))

        self.stream = sd.InputStream(
            device=device, channels=1, samplerate=rate, dtype="float32", callback=callback
        )
        self.opened_at = 0.0

    def __enter__(self) -> Capture:
        self.opened_at = time.monotonic()
        self.stream.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stream.stop()
        self.stream.close()

    def audio(self) -> np.ndarray:
        with self.lock:
            blocks = [b for _, b in self.blocks]
        return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)

    def index_at(self, moment: float) -> int:
        """Index of the sample captured at a monotonic time (block timing, so ±1 block)."""
        count = 0
        with self.lock:
            blocks = list(self.blocks)
        for arrived, block in blocks:
            if arrived >= moment:
                back = int((arrived - moment) * self.rate)
                return count + max(0, len(block) - back)
            count += len(block)
        return count

    def first_signal(self, threshold: float = 1e-4) -> float | None:
        """Seconds from opening the stream to the first sample that isn't digital silence."""
        with self.lock:
            blocks = list(self.blocks)
        for arrived, block in blocks:
            loud = np.flatnonzero(np.abs(block) > threshold)
            if loud.size:
                return arrived - (len(block) - loud[0]) / self.rate - self.opened_at
        return None


def cmd_devices(args: argparse.Namespace) -> None:
    import sounddevice as sd

    print(sd.query_devices())


class Tone:
    """A quiet 440 Hz tone on an output stream, counting the stream's underflows and errors."""

    def __init__(self, device: int, rate: int) -> None:
        import sounddevice as sd

        self.rate = rate
        self.phase = 0
        self.glitches = 0
        self.stream = sd.OutputStream(
            device=device, channels=1, samplerate=rate, callback=self.callback
        )

    def callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            self.glitches += 1
        t = (np.arange(frames) + self.phase) / self.rate
        outdata[:, 0] = 0.03 * np.sin(2 * np.pi * 440 * t)
        self.phase += frames

    def __enter__(self) -> Tone:
        self.stream.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stream.stop()
        self.stream.close()


def cmd_switch(args: argparse.Namespace) -> None:
    """Open the mic while a quiet tone plays, as Earshot does when an answer window opens."""
    in_dev, out_dev = find_device(args.device, "input"), find_device(args.device, "output")
    print("A quiet tone plays; listen for the glitch when the mic opens.")
    first_block, first_sound = [], []
    for trial in range(1, args.trials + 1):
        with Tone(out_dev, rate_of(out_dev)) as tone:
            time.sleep(3.0)  # high-quality (A2DP) playback settles
            with Capture(in_dev, rate_of(in_dev)) as capture:
                time.sleep(4.0)
            time.sleep(1.0)
        block = capture.blocks[0][0] - capture.opened_at if capture.blocks else None
        sound = capture.first_signal()
        if block is not None:
            first_block.append(block * 1000)
        if sound is not None:
            first_sound.append(sound * 1000)
        block_ms = "—" if block is None else f"{block * 1000:.0f} ms"
        sound_ms = "—" if sound is None else f"{sound * 1000:.0f} ms"
        print(
            f"  trial {trial}: first block {block_ms}, first live sample {sound_ms}, "
            f"output glitches {tone.glitches}"
        )
        time.sleep(args.gap)  # let the link return to high-quality mode
    if first_sound:
        print(
            f"\nMic live after: median {statistics.median(first_sound):.0f} ms, "
            f"max {max(first_sound):.0f} ms (first block median "
            f"{statistics.median(first_block):.0f} ms)"
        )


def measure_leak(
    segment: np.ndarray, reference: np.ndarray, floor: np.ndarray, rate: int
) -> dict[str, float]:
    """Find the played reference inside the recorded segment: delay, gain and level over the floor.

    `segment` starts when playback was started and runs at least as long as `reference`.
    """
    from scipy.signal import correlate

    xcorr = correlate(segment, reference, mode="valid")
    lag = int(np.argmax(np.abs(xcorr)))
    aligned = segment[lag : lag + len(reference)]
    gain = float(np.dot(aligned, reference) / np.dot(reference, reference))
    return {
        "delay_ms": lag / rate * 1000,
        "gain_db": db(abs(gain)),
        "correlation": float(np.corrcoef(aligned, reference)[0, 1]),
        "above_floor_db": db(rms(gain * reference)) - db(rms(floor)),
    }


def cmd_leak(args: argparse.Namespace) -> None:
    """Play a sweep through the AirPods while recording their mic; you stay silent."""
    import sounddevice as sd
    from scipy.signal import chirp

    in_dev, out_dev = find_device(args.device, "input"), find_device(args.device, "output")
    in_rate = rate_of(in_dev)
    print("Stay quiet for about 8 seconds.")
    with Capture(in_dev, in_rate) as capture:
        time.sleep(2.5)  # headset-mode switch, then the noise floor
        out_rate = rate_of(out_dev)  # after the switch: the headset-mode rate
        t = np.arange(int(3.0 * out_rate)) / out_rate
        sweep = (args.level * chirp(t, f0=300, t1=3.0, f1=6000, method="logarithmic")).astype(
            np.float32
        )
        played_at = time.monotonic()
        sd.play(sweep, out_rate, device=out_dev)
        sd.wait()
        time.sleep(1.5)
    recording = capture.audio()
    start = capture.index_at(played_at)
    floor = recording[capture.index_at(capture.opened_at + 1.5) : start]
    reference = resample(sweep, out_rate, in_rate)
    segment = recording[start : start + len(reference) + in_rate]  # up to 1 s of delay
    if len(segment) < len(reference):
        sys.exit("Recording too short; try again.")
    leak = measure_leak(segment, reference, floor, in_rate)
    write_wav(OUT / "leak" / "recording.wav", recording, in_rate)
    print(f"Output → mic delay:   {leak['delay_ms']:.0f} ms (Bluetooth out, air, Bluetooth in)")
    print(f"Leak gain:            {leak['gain_db']:.1f} dB (correlation {leak['correlation']:.2f})")
    print(f"Leak above floor:     {leak['above_floor_db']:.1f} dB")
    print(
        "Positive 'above floor' means the mic clearly hears playback: barge-in and the answer "
        "window both need care (P-06)."
    )


def make_prompt(text: str, path: Path) -> tuple[np.ndarray, int]:
    subprocess.run(["say", "-o", str(path), "--data-format=LEI16@24000", text], check=True)
    with wave.open(str(path), "rb") as f:
        rate = f.getframerate()
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32768, rate


def cmd_selfcheck(args: argparse.Namespace) -> None:
    """Play each prompt, then check answer windows cut at several delays after it ends."""
    import sounddevice as sd

    in_dev, out_dev = find_device(args.device, "input"), find_device(args.device, "output")
    in_rate = rate_of(in_dev)
    asr = None
    if args.asr:
        from mlx_audio.stt.utils import load as load_stt

        asr = load_stt(args.model)
    guards = [int(g) for g in args.guards.split(",")]
    print("Stay quiet: every answer window should be empty.\n")
    print(f"{'prompt':6} {'guard':>6} {'pre-roll':>8} {'level':>9}  transcript → intent")
    found_approval = False
    with tempfile.TemporaryDirectory() as tmp, Capture(in_dev, in_rate) as capture:
        time.sleep(2.0)  # warm mic, as Earshot keeps it while an approval is pending
        floor_db = db(rms(capture.audio()[-in_rate:]))
        for name, (text, challenge) in PROMPTS.items():
            prompt, prompt_rate = make_prompt(text, Path(tmp) / f"{name}.wav")
            for guard in guards:
                sd.play(prompt, prompt_rate, device=out_dev)
                sd.wait()
                ended_at = time.monotonic()  # playback has ended on the Mac's side
                time.sleep(guard / 1000 + WINDOW_S + 0.3)
                recording = capture.audio()
                start = capture.index_at(ended_at + guard / 1000)
                for pre_roll in (False, True):
                    first = start - int(PRE_ROLL_S * in_rate) if pre_roll else start
                    window = recording[max(first, 0) : start + int(WINDOW_S * in_rate)]
                    level = db(rms(window)) - floor_db
                    path = OUT / "selfcheck" / f"{name}-guard{guard}-preroll{int(pre_roll)}.wav"
                    write_wav(path, resample(window, in_rate, 16_000), 16_000)
                    heard, meaning = "", ""
                    if asr is not None:
                        heard = asr.generate(str(path)).text
                        meaning = intent(heard, challenge)
                        found_approval |= meaning == "approve"
                    print(
                        f"{name:6} {guard:>4}ms {'yes' if pre_roll else 'no':>8} "
                        f"{level:+7.1f}dB  {heard!r} → {meaning}"
                    )
                time.sleep(1.0)
    print(f"\nLevel is relative to the room's noise floor. Windows saved in {OUT / 'selfcheck'}.")
    if asr is not None:
        print(
            "FAIL: Earshot heard itself approve." if found_approval else "No self-approval heard."
        )


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("This spike drives CoreAudio devices; run it on the Mac.")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--device", default="AirPods", help="part of the AirPods' device name")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices").set_defaults(func=cmd_devices)
    switch = commands.add_parser("switch")
    switch.add_argument("--trials", type=int, default=5)
    switch.add_argument("--gap", type=float, default=6.0, help="seconds between trials")
    switch.set_defaults(func=cmd_switch)
    leak = commands.add_parser("leak")
    leak.add_argument("--level", type=float, default=0.3, help="sweep amplitude, 0 to 1")
    leak.set_defaults(func=cmd_leak)
    selfcheck = commands.add_parser("selfcheck")
    selfcheck.add_argument("--guards", default="0,100,250,500", help="ms after playback ends")
    selfcheck.add_argument("--asr", action="store_true", help="transcribe windows with Parakeet")
    selfcheck.add_argument("--model", default="mlx-community/parakeet-tdt-0.6b-v2")
    selfcheck.set_defaults(func=cmd_selfcheck)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
