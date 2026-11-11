"""The voice on a Mac: Kokoro speaks, the AirPods mic listens, Parakeet and Whisper transcribe.

macOS on Apple Silicon only; install with `uv sync --group voice`. Everything heavy is imported
lazily, so the daemon starts without it and the rest of Earshot runs anywhere.

- Speaking: a session chime, then Kokoro (mlx-audio), clause by clause, at 1.1x. The next clause
  is made while the chime or the last clause plays, so the first words come sooner. The espeak
  fallback is switched off, so words Kokoro can't pronounce are reported by `can_say` and
  spelled out by the narrator (D-022, D-024). Before speaking, the output must be the headset.
- Listening: the mic opens when an approval starts and stays warm while it's asked (Q-2). Only
  audio from after playback ends, plus a short guard, counts (D-015). `endpoint.py` finds the
  reply; one that began before the window is never parsed, and Silero VAD must hear speech in
  it, or it's ignored as noise (P-20). A short tone marks when to answer; the window opens after
  it (D-028). Talking while Earshot speaks stops playback (barge-in),
  but only once Silero hears speech: a noise or a click in the headset doesn't.
- Recognition: Parakeet hears every answer; only when its answer is unclear does Whisper listen
  again to the same audio (D-017). Both are quantised at load (milestone 8), to keep Earshot
  under the 3 GB footprint: on Step 0's recordings, 8-bit Parakeet hears 109 of 110 replies word
  for word as the full model does, and makes no false approvals.
- The voiceprint (`voiceprint.py`) scores every answer once a profile is enrolled (`earshot
  enroll`); tier 2 needs a match, and tier 1's scores go to the audit log (milestone 6).
- With the signed helper connected (`helper.py`, milestone 7), the mic comes from it, at 16 kHz,
  and so does head motion: a shake in the answer window hands the request to the screen, and with
  `nods` on, a strict double nod approves at tier 1 (D-018). Without it, sounddevice captures.
- With `keep_audio` (`earshotd --keep-audio`), each reply's clip is saved with what became of
  it, to tune the guards on real failures. Off by default: audio isn't stored (P-20).
- Models download the first time. Once all of them are cached, loading runs with the Hub offline,
  so nothing leaves the Mac, not even an update check.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import queue
import threading
import time
import wave
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from earshot.voice import endpoint, gestures, intents, voiceprint
from earshot.voice.decider import CUT_OFF, Heard, Speaker
from earshot.voice.helper import HelperLink

log = logging.getLogger("earshot.voice")

TTS_MODEL = "mlx-community/Kokoro-82M-bf16"
TTS_RATE = 24_000
ASR_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
SECOND_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
VAD_MODEL = "mlx-community/silero-vad"
ASR_BITS = 8  # Parakeet's weights: 2.51 GB as float32, 0.97 GB at 8 bits (milestone 8)
SECOND_BITS = 8  # Whisper's, loaded only when needed: 1.62 GB as float16, 0.87 GB at 8 bits
ASR_RATE = 16_000
FRAME_S = 0.02
GUARD_S = 0.15  # output delay after playback ends (D-015)
PRE_ROLL_S = 0.25
HELPER_GAP_S = 0.25  # a later chunk than this starts the helper's clock again
CLAUSES = r"(?<=[.?!,:;])\s+"  # Kokoro speaks clause by clause: short first clauses start sooner
MIN_SPEECH_MS = 100  # Silero's default of 250 ms is longer than a quick "no"
BARGE_LEVEL = 0.05  # this loud while Earshot speaks, and Silero checks for speech
BARGE_LOOK_S = 0.5  # how much of the mic Silero hears for that check
LISTEN_TONE_HZ = 1318.5  # E6, above every session chime
LISTEN_TONE_S = 0.1
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


def listening_tone(rate: int = TTS_RATE) -> list[float]:
    """The short, soft tone that says "answer now", made in code like the chimes (D-028)."""
    count = int(rate * LISTEN_TONE_S)
    return [
        0.15 * math.sin(math.pi * n / count) * math.sin(2 * math.pi * LISTEN_TONE_HZ * n / rate)
        for n in range(count)
    ]


def _quantized(model: Any, bits: int) -> Any:
    """`model` with its linear layers quantised to `bits`, in place (MLX)."""
    import mlx.core as mx
    import mlx.nn as nn

    nn.quantize(model, group_size=64, bits=bits)  # type: ignore[attr-defined]  # not in the stubs
    mx.eval(model.parameters())
    mx.clear_cache()  # MLX keeps the full-size weights' memory cached otherwise
    return model


class MacVoice:
    def __init__(
        self,
        headset: str = "AirPods",
        voice: str = "af_heart",
        speed: float = 1.1,
        keep_audio: Path | None = None,
        profile: Path | None = None,
        models: Path | None = None,
        helper: HelperLink | None = None,
        nods: bool = False,
    ):
        self.headset = headset
        self.helper = helper  # the signed helper's link, used whenever it's connected
        self.nods = nods  # D-018: off unless switched on
        if helper is not None:
            helper.on_audio = self._helper_audio
        self.keep_audio = keep_audio
        self.profile_path = profile  # the enrolled voiceprint, if there is one
        self.models = models  # where the voiceprint's model is
        self._profile: voiceprint.Profile | None = None
        self._embedder: voiceprint.Embedder | None = None
        self._kept: str | None = None  # the last clip saved, for its transcript
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
        self._helper_end = 0.0  # when the helper's last chunk ended, by its own samples
        self._lock = threading.Lock()
        self._audio = threading.Lock()  # PortAudio isn't thread-safe: one stream change at a time
        self._mlx = threading.RLock()  # nor is MLX: one model runs at a time, across threads
        self._playing = threading.Event()
        self._loud = threading.Event()  # something loud while Earshot speaks: speech or noise?
        self._barge = threading.Event()  # it was speech: you're talking over Earshot
        self._ignored = 0  # noises heard while speaking, for the log

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
        self._asr = _quantized(load_stt(ASR_MODEL), ASR_BITS)
        self._vad = load_vad(VAD_MODEL)
        log.info("voice ready: %s, %s and %s", TTS_MODEL, ASR_MODEL, VAD_MODEL)
        self._load_voiceprint()

    def _load_voiceprint(self) -> None:
        if self.profile_path is None or self.models is None:
            return
        profile = voiceprint.load(self.profile_path)
        model = self.models / voiceprint.MODEL
        if profile is None or not model.exists():
            log.info("no voiceprint enrolled: tier 2 stays on the screen")
            return
        self._embedder = voiceprint.Embedder(model)
        self._profile = profile
        log.info(
            "voiceprint ready: %d phrases, threshold %.2f%s",
            profile.phrases,
            profile.threshold,
            "" if profile.calibrated else " (not yet calibrated)",
        )

    def speaker_ready(self) -> bool:
        """Whether a voiceprint is enrolled, so tier 2 can be asked by voice."""
        return self._profile is not None and self._embedder is not None

    def speaker(self, clip: Any) -> Speaker | None:
        """How much a 16 kHz clip sounds like you, once a voiceprint is enrolled."""
        if self._profile is None or self._embedder is None:
            return None
        score = voiceprint.cosine(self._embedder.embed(clip), self._profile.embedding)
        return Speaker(round(score, 4), voiceprint.verdict(score, self._profile))

    def record_phrase(self, prompt: str, seconds: float = 8.0) -> Any:
        """Say `prompt`, then capture one reply: 16 kHz audio, or None. For `earshot enroll`."""
        self._open_mic()
        self._say(prompt, None, threading.Event())
        clip = self._capture(seconds)
        return None if clip is None or clip is CUT_OFF else clip

    def _second_model(self) -> Any:
        if self._second is None:
            from mlx_audio.stt.utils import load as load_stt

            self._second = _quantized(load_stt(SECOND_MODEL), SECOND_BITS)  # loaded on first need
        return self._second

    # Devices

    def headset_ready(self) -> bool:
        if self.helper is not None and self.helper.connected and self.helper.devices:
            return self.headset.lower() in str(self.helper.devices.get("output", "")).lower()
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

    def _helper_audio(self, data: bytes) -> None:
        """16-bit samples at 16 kHz from the helper, on the daemon's event loop.

        The helper sends about 100 ms at a time. They're cut into the 20 ms frames the endpointer
        and the window rule were tuned on (D-027), each stamped with when it ended. The samples
        themselves keep the time, so a chunk that arrives late isn't heard late; the clock starts
        again from the arrival after a gap, or when a chunk comes sooner than it says.
        """
        import numpy as np

        chunk = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
        if not chunk.size:
            return
        now = time.monotonic()
        end = self._helper_end + chunk.size / ASR_RATE
        if not now - HELPER_GAP_S <= end <= now:
            end = now
        self._helper_end = end
        size = int(ASR_RATE * FRAME_S)
        pieces = [chunk[i : i + size] for i in range(0, chunk.size, size)]
        with self._lock:
            for n, piece in enumerate(pieces):
                self._frames.append((end - (len(pieces) - 1 - n) * FRAME_S, piece))
        if self._playing.is_set() and any(
            float(np.sqrt(np.mean(piece**2))) > BARGE_LEVEL for piece in pieces
        ):
            self._loud.set()

    def _open_mic(self) -> None:
        if self.helper is not None and self.helper.connected:
            with self._audio:
                if self._mic is None:
                    self.helper.want(mic=True, motion=True)
                    self.helper.motion.clear()
                    self._helper_end = 0.0
                    self._mic, self._mic_rate = "helper", ASR_RATE
                    log.info("mic open: through the helper, at %d Hz", ASR_RATE)
            return
        import numpy as np
        import sounddevice as sd

        def callback(data: Any, frames: int, when: Any, status: Any) -> None:
            chunk = np.array(data[:, 0], dtype=np.float32)
            with self._lock:
                self._frames.append((time.monotonic(), chunk))
            if self._playing.is_set() and float(np.sqrt(np.mean(chunk**2))) > BARGE_LEVEL:
                self._loud.set()  # _talked_over() decides whether it's you

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
            if self._mic == "helper":
                if self.helper is not None:
                    self.helper.want(mic=False, motion=False)
                self._mic = None
            elif self._mic is not None:
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
            self._loud.clear()
            self._barge.clear()
            self._ignored = 0
            self._playing.set()
            halt = threading.Event()
            chunks: queue.Queue[Any] = queue.Queue(maxsize=3)
            producer = threading.Thread(
                target=self._produce, args=(text, chunks, halt), daemon=True
            )
            producer.start()  # Kokoro works on the first clause while the chime plays
            began = time.monotonic()
            spoken = waited = 0.0
            try:
                if chime_index is not None:
                    self._play(np.array(chime(chime_index), dtype=np.float32), stop)
                while not (stop.is_set() or self._talked_over()):
                    asked = time.monotonic()
                    try:
                        chunk = chunks.get(timeout=0.05)  # short, so a cancel stops it at once
                    except queue.Empty:
                        waited += time.monotonic() - asked
                        continue
                    waited += time.monotonic() - asked
                    if chunk is None or stop.is_set() or self._talked_over():
                        break
                    spoken += len(chunk) / TTS_RATE
                    self._play(chunk, stop)
            finally:
                halt.set()
                with contextlib.suppress(queue.Empty):
                    while True:  # let a producer blocked on a full queue see the halt
                        chunks.get_nowait()
                producer.join(timeout=5)
                self._playing.clear()
                sd.stop()
                if self._ignored:
                    log.info("ignored %d noises while speaking", self._ignored)
                log.info(
                    "spoke %.1f s of speech in %.1f s, %.1f s of it waiting for speech to be made",
                    spoken,
                    time.monotonic() - began,
                    waited,
                )

    def _produce(self, text: str, chunks: queue.Queue[Any], halt: threading.Event) -> None:
        """Make the speech clause by clause, ahead of playback; None marks the end."""
        import numpy as np

        try:
            clauses = self._tts.generate(
                text, voice=self.voice_name, speed=self.speed, split_pattern=CLAUSES
            )
            while not halt.is_set():
                with self._mlx:
                    result = next(clauses, None)
                if result is None:
                    break
                audio = np.array(result.audio, dtype=np.float32)
                while not halt.is_set():
                    with contextlib.suppress(queue.Full):
                        chunks.put(audio, timeout=0.1)
                        break
        except Exception:
            log.exception("speech couldn't be made")
        finally:
            with contextlib.suppress(queue.Full):
                chunks.put(None, timeout=1)

    def _play(self, audio: Any, stop: threading.Event) -> None:
        import sounddevice as sd

        sd.play(audio, TTS_RATE)
        end = time.monotonic() + len(audio) / TTS_RATE + 0.05
        while time.monotonic() < end:
            if stop.is_set() or self._talked_over():
                sd.stop()
                return
            time.sleep(0.01)

    def _talked_over(self) -> bool:
        """Whether you're talking over Earshot: the mic was loud, and Silero hears speech in it."""
        if self._barge.is_set() or not self._loud.is_set():
            return self._barge.is_set()
        import numpy as np

        self._loud.clear()
        with self._lock:
            since = time.monotonic() - BARGE_LOOK_S
            recent = [c for t, c in self._frames if t >= since]
        if not recent:
            return False
        clip = self._resample(np.concatenate(recent), self._mic_rate)
        loudest = round(float(np.max(np.abs(clip))), 4)
        if self.is_speech(clip):
            log.info("barge-in: speech over Earshot, peak %.4f", loudest)
            self._keep(clip, verdict="barge-in", peak=loudest)
            self._barge.set()
            return True
        self._ignored += 1
        if self._ignored == 1:
            self._keep(clip, verdict="noise while speaking", peak=loudest)
        return False

    # Listening

    async def listen(self, seconds: float) -> Heard | None:
        clip = await asyncio.to_thread(self._capture, seconds)
        if clip is None:
            return None
        if clip is CUT_OFF:
            return Heard("", CUT_OFF, 0)  # never parsed; the decider asks again
        if isinstance(clip, str):  # a gesture: "shake", or "nod" with nods on
            return Heard("", clip, 0)
        return await asyncio.to_thread(self._recognize, clip)

    def _gesture(self, since: float) -> str | None:
        """A shake, or a nod with nods on, in the head motion since `since` (D-018)."""
        if self.helper is None or not self.helper.connected:
            return None
        samples = [s for s in list(self.helper.motion) if s.t >= since]
        return gestures.detect(samples, nods=self.nods) if samples else None

    def _capture(self, seconds: float) -> Any:
        """One reply as 16 kHz audio, None if nobody spoke in the window, or CUT_OFF."""
        import numpy as np

        if self._mic is None:
            self._open_mic()
        self._tone()
        opened = time.monotonic() + GUARD_S  # nothing from before the window counts (D-015)
        deadline = opened + seconds
        motion_since = self._motion_clock()
        while True:
            time.sleep(FRAME_S)
            now = time.monotonic()
            if (gesture := self._gesture(motion_since)) is not None:
                log.info("gesture: %s", gesture)
                return gesture
            with self._lock:
                frames = [(t, c) for t, c in self._frames if t >= opened - endpoint.LEAD_QUIET_S]
            levels = [(t, float(np.sqrt(np.mean(c**2)))) for t, c in frames]
            reply = endpoint.find_reply(levels, opened, now)
            if reply is None:
                if now > deadline:
                    inside = [level for t, level in levels if t >= opened]
                    log.info(
                        "heard nothing: loudest %.4f in %d frames",
                        max(inside, default=0.0),
                        len(inside),
                    )
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
            keep = [
                c
                for t, c in frames
                if t >= opened and reply.start - PRE_ROLL_S <= t <= reply.end + 0.25
            ]
            clip = self._resample(np.concatenate(keep), self._mic_rate)
            levels_seen = {
                "seconds": round(reply.end - reply.start, 2),
                "noise": round(reply.noise, 4),
                "threshold": round(reply.threshold, 4),
                "loudest": round(reply.loudest, 4),
            }
            if reply.cut_off:
                self._kept = self._keep(clip, verdict="cut off", **levels_seen)
                return CUT_OFF
            speech = self.is_speech(clip)
            verdict = "speech" if speech else "not speech"
            self._kept = self._keep(clip, verdict=verdict, **levels_seen)
            if speech:
                return clip
            log.info("not speech: ignored")
            if now > deadline:
                return None
            opened = reply.end + FRAME_S  # listen on, after the noise

    def _tone(self) -> None:
        """Play the listening tone and wait for it to finish; the window opens after it."""
        import numpy as np
        import sounddevice as sd

        started = time.monotonic()
        with self._audio:
            sd.play(np.array(listening_tone(), dtype=np.float32), TTS_RATE)
            sd.wait()
        if (late := time.monotonic() - started - LISTEN_TONE_S) > 0.5:
            log.info("the listening tone came %.1f s late", late)

    def _motion_clock(self) -> float:
        """The helper's motion time for "now": its clock isn't the daemon's."""
        if self.helper is None or not self.helper.motion:
            return 0.0
        return self.helper.motion[-1].t

    def is_speech(self, clip: Any) -> bool:
        """Whether Silero hears speech in a 16 kHz clip: a cough, bump or breath isn't (P-20)."""
        import mlx.core as mx

        with self._mlx:
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
        with self._mlx:
            text = str(self._asr.generate(mx.array(clip)).text).strip()
        recognizer = "parakeet"
        if intents.parse(text).kind == "unclear":  # a second listen, only when unclear (D-017)
            with self._mlx:
                second = self._second_model()
                heard = second.generate(mx.array(clip), language="en", temperature=0.0)
            text = str(heard.text).strip()
            recognizer = "parakeet+whisper"
        ms = int((time.monotonic() - start) * 1000)
        kind = intents.parse(text).kind
        speaker = self.speaker(clip)
        log.info(
            "recognized: %s, by %s in %d ms%s",
            kind,
            recognizer,
            ms,
            f"; voiceprint {speaker.score:.2f}, {speaker.verdict}" if speaker else "",
        )
        if self._kept is not None:
            score = speaker.score if speaker else None
            self._keep(
                None,
                file=self._kept,
                transcript=text,
                recognizer=recognizer,
                intent=kind,
                voiceprint=score,
            )
            self._kept = None
        return Heard(text, recognizer, ms, speaker)

    def _keep(self, clip: Any, **fields: Any) -> str | None:
        """With keep_audio, save a clip as 16 kHz WAV, and a line about it in clips.jsonl."""
        if self.keep_audio is None:
            return None
        import numpy as np

        self.keep_audio.mkdir(parents=True, exist_ok=True)
        if clip is not None:
            fields = {"file": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ.wav"), **fields}
            with wave.open(str(self.keep_audio / fields["file"]), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(ASR_RATE)
                out.writeframes((np.clip(clip, -1, 1) * 32767).astype(np.int16).tobytes())
        with (self.keep_audio / "clips.jsonl").open("a", encoding="utf-8") as notes:
            notes.write(json.dumps({"ts": datetime.now(UTC).isoformat(), **fields}) + "\n")
        return fields.get("file")
