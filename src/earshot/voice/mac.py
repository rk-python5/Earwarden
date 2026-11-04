"""The voice on a Mac: Kokoro speaks, the AirPods mic listens, Parakeet and Whisper transcribe.

macOS on Apple Silicon only; install with `uv sync --group voice`. Everything heavy is imported
lazily, so the daemon starts without it and the rest of Earshot runs anywhere.

- Speaking: a session chime, then Kokoro (mlx-audio), sentence by sentence, at 1.1x. The espeak
  fallback is switched off, so words Kokoro can't pronounce are reported by `can_say` and
  spelled out by the narrator (D-022, D-024). Before speaking, the output must be the headset.
- Listening: the mic opens when an approval starts and stays warm while it's asked (Q-2). Only
  audio from after playback ends, plus a short guard, counts (D-015). Speech ends after 400 ms
  of quiet or at 6 s (D-023). Talking while Earshot speaks stops playback (barge-in).
- Recognition: Parakeet hears every answer; only when its answer is unclear does Whisper listen
  again to the same audio (D-017).
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import deque
from typing import Any

from earshot.voice import intents
from earshot.voice.decider import Heard

log = logging.getLogger("earshot.voice")

TTS_MODEL = "mlx-community/Kokoro-82M-bf16"
TTS_RATE = 24_000
ASR_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
SECOND_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
ASR_RATE = 16_000
FRAME_S = 0.02
END_SILENCE_S = 0.4
MAX_SPEECH_S = 6.0
GUARD_S = 0.15  # output delay after playback ends (D-015)
PRE_ROLL_S = 0.25
CHIME_NOTES = [523.25, 587.33, 659.25, 698.46, 783.99, 880.0, 987.77, 1046.5]


def chime(index: int, rate: int = TTS_RATE) -> list[float]:
    """A short two-note chime per session, made in code (no audio files to license)."""
    base = CHIME_NOTES[index % len(CHIME_NOTES)]
    samples: list[float] = []
    for frequency, seconds in ((base, 0.09), (base * 1.25, 0.12)):
        count = int(rate * seconds)
        for n in range(count):
            envelope = math.sin(math.pi * n / count)
            samples.append(0.2 * envelope * math.sin(2 * math.pi * frequency * n / rate))
    return samples


class MacVoice:
    def __init__(self, headset: str = "AirPods", voice: str = "af_heart", speed: float = 1.1):
        self.headset = headset
        self.voice_name = voice
        self.speed = speed
        self._tts: Any = None
        self._g2p: Any = None
        self._asr: Any = None
        self._second: Any = None
        self._mic: Any = None
        self._mic_rate = 0
        self._frames: deque[tuple[float, Any]] = deque(maxlen=int(30 / FRAME_S))
        self._lock = threading.Lock()
        self._playing = threading.Event()
        self._barge = threading.Event()

    # Loading

    def load(self) -> None:
        """Load and warm the models. Slow the first time: they download into .tools/."""
        import mlx.core as mx  # noqa: F401 - fail early off Apple Silicon
        from mlx_audio.stt.utils import load as load_stt
        from mlx_audio.tts.utils import load as load_tts

        self._tts = load_tts(TTS_MODEL)
        for _ in self._tts.generate("Ready.", voice=self.voice_name, speed=self.speed):
            pass
        pipeline = self._tts._get_pipeline("a")
        pipeline.g2p.fallback = None  # no espeak at runtime (D-022)
        self._g2p = pipeline.g2p
        self._asr = load_stt(ASR_MODEL)
        log.info("voice ready: %s and %s", TTS_MODEL, ASR_MODEL)

    def _second_model(self) -> Any:
        if self._second is None:
            from mlx_audio.stt.utils import load as load_stt

            self._second = load_stt(SECOND_MODEL)  # loaded on first need, to save memory
        return self._second

    # Devices

    def headset_ready(self) -> bool:
        import sounddevice as sd

        try:
            if self._mic is None:  # PortAudio lists devices only at start; refresh when idle
                sd._terminate()
                sd._initialize()
            output: Any = sd.query_devices(kind="output")
        except Exception:
            log.exception("couldn't read the output device")
            return False
        return self.headset.lower() in str(output["name"]).lower()

    def _input_device(self) -> int:
        import sounddevice as sd

        devices: Any = sd.query_devices()
        for index, device in enumerate(devices):
            if self.headset.lower() in device["name"].lower() and device["max_input_channels"] > 0:
                return index
        raise RuntimeError(f"no input device matching {self.headset!r}")

    # Pronunciation

    def can_say(self, word: str) -> bool:
        if self._g2p is None:
            return True
        try:
            _, tokens = self._g2p(word)
        except Exception:
            return True
        return all(getattr(t, "phonemes", None) for t in tokens if str(t.text).strip())

    # Microphone

    async def open_mic(self) -> None:
        await asyncio.to_thread(self._open_mic)

    def _open_mic(self) -> None:
        import numpy as np
        import sounddevice as sd

        if self._mic is not None:
            return
        device = self._input_device()
        rate = int(sd.query_devices(device)["default_samplerate"])

        def callback(data: Any, frames: int, when: Any, status: Any) -> None:
            chunk = np.array(data[:, 0], dtype=np.float32)
            with self._lock:
                self._frames.append((time.monotonic(), chunk))
            if self._playing.is_set() and float(np.sqrt(np.mean(chunk**2))) > 0.05:
                self._barge.set()  # you started talking over Earshot

        self._mic = sd.InputStream(
            device=device,
            channels=1,
            samplerate=rate,
            dtype="float32",
            blocksize=int(rate * FRAME_S),
            callback=callback,
        )
        self._mic_rate = rate
        self._mic.start()

    async def close_mic(self) -> None:
        await asyncio.to_thread(self._close_mic)

    def _close_mic(self) -> None:
        if self._mic is not None:
            self._mic.stop()
            self._mic.close()
            self._mic = None
        with self._lock:
            self._frames.clear()

    # Speaking

    async def say(self, text: str, chime: int | None = None) -> None:
        stop = threading.Event()
        try:
            await asyncio.to_thread(self._say, text, chime, stop)
        except asyncio.CancelledError:
            stop.set()  # the request was answered elsewhere: fall silent at once
            raise

    def _say(self, text: str, chime_index: int | None, stop: threading.Event) -> None:
        import numpy as np
        import sounddevice as sd

        if self._tts is None:
            self.load()
        self._barge.clear()
        self._playing.set()
        try:
            if chime_index is not None:
                self._play(np.array(chime(chime_index), dtype=np.float32), stop)
            for result in self._tts.generate(
                text, voice=self.voice_name, speed=self.speed, split_pattern=r"(?<=[.?!])\s+"
            ):
                if stop.is_set() or self._barge.is_set():
                    break
                self._play(np.array(result.audio, dtype=np.float32), stop)
        finally:
            self._playing.clear()
            sd.stop()

    def _play(self, audio: Any, stop: threading.Event) -> None:
        import sounddevice as sd

        sd.play(audio, TTS_RATE)
        end = time.monotonic() + len(audio) / TTS_RATE + 0.05
        while time.monotonic() < end:
            if stop.is_set() or self._barge.is_set():
                sd.stop()
                return
            time.sleep(0.01)

    # Listening

    async def listen(self, seconds: float) -> Heard | None:
        clip = await asyncio.to_thread(self._capture, seconds)
        if clip is None:
            return None
        return await asyncio.to_thread(self._recognize, clip)

    def _capture(self, seconds: float) -> Any:
        """One answer, endpointed by energy, or None if nobody spoke in the window."""
        import numpy as np

        if self._mic is None:
            self._open_mic()
        opened = time.monotonic() + GUARD_S  # nothing from before the window counts (D-015)
        deadline = opened + seconds
        started: float | None = None
        last_voice = 0.0
        noise = 0.003
        while True:
            time.sleep(FRAME_S)
            now = time.monotonic()
            with self._lock:
                frames = [(t, c) for t, c in self._frames if t >= opened]
            if not frames:
                if now > deadline:
                    return None
                continue
            levels = [(t, float(np.sqrt(np.mean(c**2)))) for t, c in frames]
            if started is None:
                quiet = sorted(level for _, level in levels)[: max(1, len(levels) // 10)]
                noise = max(min(quiet) if quiet else noise, 0.001)
            threshold = max(noise * 4, 0.01)
            for t, level in levels:
                if level > threshold:
                    started = started or t
                    last_voice = t
            if started is None and now > deadline:
                return None
            if started is not None and (
                now - last_voice >= END_SILENCE_S or now - started >= MAX_SPEECH_S
            ):
                keep = [c for t, c in frames if started - PRE_ROLL_S <= t <= last_voice + 0.25]
                return self._resample(np.concatenate(keep), self._mic_rate)

    @staticmethod
    def _resample(audio: Any, rate: int) -> Any:
        import numpy as np

        if rate == ASR_RATE:
            return audio
        duration = len(audio) / rate
        target = np.linspace(0, duration, int(duration * ASR_RATE), endpoint=False)
        source = np.arange(len(audio)) / rate
        return np.interp(target, source, audio).astype(np.float32)

    def _recognize(self, clip: Any) -> Heard:
        import mlx.core as mx

        start = time.monotonic()
        text = str(self._asr.generate(mx.array(clip)).text).strip()
        recognizer = "parakeet"
        if intents.parse(text).kind == "unclear":  # a second listen, only when unclear (D-017)
            second = self._second_model()
            text = str(second.generate(mx.array(clip), language="en", temperature=0.0).text).strip()
            recognizer = "parakeet+whisper"
        return Heard(text, recognizer, int((time.monotonic() - start) * 1000))
