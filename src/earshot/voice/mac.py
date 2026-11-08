"""The voice on a Mac: Kokoro speaks, the AirPods mic listens, Parakeet and Whisper transcribe.

macOS on Apple Silicon only; install with `uv sync --group voice`. Everything heavy is imported
lazily, so the daemon starts without it and the rest of Earshot runs anywhere.

- Speaking: a session chime, then Kokoro (mlx-audio), sentence by sentence, at 1.1x. The espeak
  fallback is switched off, so words Kokoro can't pronounce are reported by `can_say` and
  spelled out by the narrator (D-022, D-024). Before speaking, the output must be the headset.
- Listening: the mic opens when an approval starts and stays warm while it's asked (Q-2). Only
  audio from after playback ends, plus a short guard, counts (D-015). `endpoint.py` finds the
  reply; one that began before the window is never parsed, and Silero VAD must hear speech in
  it, or it's ignored as noise (P-20). Talking while Earshot speaks stops playback (barge-in).
- Recognition: Parakeet hears every answer; only when its answer is unclear does Whisper listen
  again to the same audio (D-017).
- Models download the first time. Once all of them are cached, loading runs with the Hub offline,
  so nothing leaves the Mac, not even an update check.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from earshot.voice import endpoint, intents
from earshot.voice.decider import Heard

log = logging.getLogger("earshot.voice")

TTS_MODEL = "mlx-community/Kokoro-82M-bf16"
TTS_RATE = 24_000
ASR_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
SECOND_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
VAD_MODEL = "mlx-community/silero-vad"
ASR_RATE = 16_000
FRAME_S = 0.02
GUARD_S = 0.15  # output delay after playback ends (D-015)
PRE_ROLL_S = 0.25
MIN_SPEECH_MS = 100  # Silero's default of 250 ms is longer than a quick "no"
CUT_OFF = object()  # what _capture returns for a reply that began before the window (P-20)
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


def hub_cache() -> Path:
    """Where huggingface_hub keeps models: HF_HUB_CACHE, else HF_HOME/hub (dev/activate sets it)."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return Path(os.environ.get("HF_HOME") or cache_home / "huggingface") / "hub"


def models_cached(cache: Path) -> bool:
    """Whether every model's weights are downloaded, so loading needn't ask the Hub for updates."""
    return all(
        any((cache / f"models--{model.replace('/', '--')}" / "snapshots").glob("*/*.safetensors"))
        for model in (TTS_MODEL, ASR_MODEL, SECOND_MODEL, VAD_MODEL)
    )


class MacVoice:
    def __init__(self, headset: str = "AirPods", voice: str = "af_heart", speed: float = 1.1):
        self.headset = headset
        self.voice_name = voice
        self.speed = speed
        self._tts: Any = None
        self._g2p: Any = None
        self._asr: Any = None
        self._second: Any = None
        self._vad: Any = None
        self._mic: Any = None
        self._mic_rate = 0
        self._frames: deque[tuple[float, Any]] = deque(maxlen=int(30 / FRAME_S))
        self._lock = threading.Lock()
        self._audio = threading.Lock()  # PortAudio isn't thread-safe: one stream change at a time
        self._playing = threading.Event()
        self._barge = threading.Event()

    # Loading

    def load(self) -> None:
        """Load and warm the models. Slow the first time: they download into .tools/."""
        if models_cached(hub_cache()):  # read at import, so before mlx_audio brings in the Hub
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import mlx.core as mx  # noqa: F401 - fail early off Apple Silicon
        from mlx_audio.stt.utils import load as load_stt
        from mlx_audio.tts.utils import load as load_tts
        from mlx_audio.vad import load as load_vad

        self._tts = load_tts(TTS_MODEL)
        for _ in self._tts.generate("Ready.", voice=self.voice_name, speed=self.speed):
            pass
        pipeline = self._tts._get_pipeline("a")
        pipeline.g2p.fallback = None  # no espeak at runtime (D-022)
        self._g2p = pipeline.g2p
        self._asr = load_stt(ASR_MODEL)
        self._vad = load_vad(VAD_MODEL)
        log.info("voice ready: %s, %s and %s", TTS_MODEL, ASR_MODEL, VAD_MODEL)

    def _second_model(self) -> Any:
        if self._second is None:
            from mlx_audio.stt.utils import load as load_stt

            self._second = load_stt(SECOND_MODEL)  # loaded on first need, to save memory
        return self._second

    # Devices

    def headset_ready(self) -> bool:
        import sounddevice as sd

        try:
            # PortAudio lists devices only at start, so refresh it, but never under a live
            # stream: only while the mic is closed and nothing is speaking.
            if self._audio.acquire(blocking=False):
                try:
                    if self._mic is None:
                        sd._terminate()
                        sd._initialize()
                finally:
                    self._audio.release()
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

        def callback(data: Any, frames: int, when: Any, status: Any) -> None:
            chunk = np.array(data[:, 0], dtype=np.float32)
            with self._lock:
                self._frames.append((time.monotonic(), chunk))
            if self._playing.is_set() and float(np.sqrt(np.mean(chunk**2))) > 0.05:
                self._barge.set()  # you started talking over Earshot

        with self._audio:
            if self._mic is not None:
                return
            device = self._input_device()
            info: Any = sd.query_devices(device)
            rate = int(info["default_samplerate"])
            log.info("mic open: %s at %d Hz", info["name"], rate)
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
        with self._audio:
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

        # One voice at a time: a cancelled one finishes, and its final sd.stop() runs, before
        # the next starts, or that stop would cut off the next request's speech.
        with self._audio:
            if stop.is_set():
                return
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
        if clip is CUT_OFF:
            return Heard("", "cut off", 0)  # never parsed: it's unclear, so it's asked again
        return await asyncio.to_thread(self._recognize, clip)

    def _capture(self, seconds: float) -> Any:
        """One reply as 16 kHz audio, None if nobody spoke in the window, or CUT_OFF."""
        import numpy as np

        if self._mic is None:
            self._open_mic()
        opened = time.monotonic() + GUARD_S  # nothing from before the window counts (D-015)
        deadline = opened + seconds
        while True:
            time.sleep(FRAME_S)
            now = time.monotonic()
            with self._lock:
                frames = [(t, c) for t, c in self._frames if t >= opened - endpoint.LEAD_QUIET_S]
            levels = [(t, float(np.sqrt(np.mean(c**2)))) for t, c in frames]
            reply = endpoint.find_reply(levels, opened, now)
            if reply is None:
                if now > deadline:
                    inside = [level for t, level in levels if t >= opened]
                    log.info("heard nothing: loudest %.4f", max(inside, default=0.0))
                    return None
                continue
            if reply.end is None:
                continue  # still talking, even past the deadline
            log.info(
                "speech for %.1f s: noise %.4f, threshold %.4f, loudest %.4f%s",
                reply.end - reply.start,
                reply.noise,
                reply.threshold,
                reply.loudest,
                ", began before the window" if reply.cut_off else "",
            )
            if reply.cut_off:
                return CUT_OFF
            keep = [
                c
                for t, c in frames
                if t >= opened and reply.start - PRE_ROLL_S <= t <= reply.end + 0.25
            ]
            clip = self._resample(np.concatenate(keep), self._mic_rate)
            if self.is_speech(clip):
                return clip
            log.info("not speech: ignored")
            if now > deadline:
                return None
            opened = reply.end + FRAME_S  # listen on, after the noise

    def is_speech(self, clip: Any) -> bool:
        """Whether Silero hears speech in a 16 kHz clip: a cough, bump or breath isn't (P-20)."""
        import mlx.core as mx

        found = self._vad.get_speech_timestamps(
            mx.array(clip), sample_rate=ASR_RATE, min_speech_duration_ms=MIN_SPEECH_MS
        )
        return bool(found)

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
        ms = int((time.monotonic() - start) * 1000)
        log.info("recognized: %s, by %s in %d ms", intents.parse(text).kind, recognizer, ms)
        return Heard(text, recognizer, ms)
