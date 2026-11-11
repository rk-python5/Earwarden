"""The Mac voice's model cache check, audio locking and kept clips, with sounddevice faked."""

from __future__ import annotations

import json
import sys
import threading
import time
import types
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from earshot.voice import mac
from earshot.voice.mac import MacVoice


def cache_model(cache: Path, model: str) -> None:
    snapshot = cache / f"models--{model.replace('/', '--')}" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"")


def test_models_cached_needs_every_models_weights(tmp_path: Path) -> None:
    assert not mac.models_cached(tmp_path)
    cache_model(tmp_path, mac.TTS_MODEL)
    cache_model(tmp_path, mac.ASR_MODEL)
    assert not mac.models_cached(tmp_path)  # Whisper is loaded later, but must be there too
    cache_model(tmp_path, mac.SECOND_MODEL)
    assert not mac.models_cached(tmp_path)
    cache_model(tmp_path, mac.VAD_MODEL)
    assert mac.models_cached(tmp_path)


def test_hub_cache_follows_the_hugging_face_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert mac.hub_cache() == tmp_path / "xdg" / "huggingface" / "hub"
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert mac.hub_cache() == tmp_path / "hf" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    assert mac.hub_cache() == tmp_path / "hub"


class Clip(list[float]):
    def __init__(self, tag: str) -> None:
        super().__init__([0.0] * 240)  # 10 ms at 24 kHz
        self.tag = tag


class FakeSounddevice(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("sounddevice")
        self.events: list[str] = []
        self.refreshes = 0

    def play(self, audio: Clip, rate: int) -> None:
        self.events.append(f"play {audio.tag}")

    def stop(self) -> None:
        self.events.append("stop")

    def _terminate(self) -> None:
        self.refreshes += 1

    def _initialize(self) -> None:
        pass

    def query_devices(self, kind: str) -> dict[str, Any]:
        return {"name": "rehaan's AirPods Pro"}


class GatedTTS:
    """Speaks two sentences of each text, holding before the second one until `go` is set."""

    def __init__(self) -> None:
        self.waiting = threading.Event()
        self.go = threading.Event()

    def generate(self, text: str, **kwargs: Any) -> Iterator[types.SimpleNamespace]:
        yield types.SimpleNamespace(audio=Clip(f"{text} 1"))
        self.waiting.set()
        self.go.wait(5)
        yield types.SimpleNamespace(audio=Clip(f"{text} 2"))


@pytest.fixture
def sd(monkeypatch: pytest.MonkeyPatch) -> FakeSounddevice:
    fake = FakeSounddevice()
    numpy = types.SimpleNamespace(array=lambda data, dtype=None: data, float32="float32")
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    return fake


def speak(voice: MacVoice, text: str, stop: threading.Event) -> threading.Thread:
    thread = threading.Thread(target=voice._say, args=(text, None, stop))
    thread.start()
    return thread


def test_a_cancelled_voice_stops_before_the_next_one_speaks(sd: FakeSounddevice) -> None:
    voice = MacVoice()
    tts = voice._tts = GatedTTS()
    first_stop = threading.Event()
    first = speak(voice, "first", first_stop)
    assert tts.waiting.wait(5)
    for _ in range(100):  # until the first clause has played (speech is made ahead of playback)
        if "play first 1" in sd.events:
            break
        time.sleep(0.01)
    time.sleep(0.1)
    first_stop.set()  # the request was answered on the screen
    second = speak(voice, "second", threading.Event())
    time.sleep(0.1)  # time for the second voice to start, if nothing held it back
    tts.go.set()
    first.join(5)
    second.join(5)
    assert sd.events == ["play first 1", "stop", "play second 1", "play second 2", "stop"]


def test_devices_refresh_only_when_no_stream_is_open(sd: FakeSounddevice) -> None:
    voice = MacVoice()
    tts = voice._tts = GatedTTS()
    speaking = speak(voice, "hello", threading.Event())
    assert tts.waiting.wait(5)
    assert voice.headset_ready()
    assert sd.refreshes == 0  # restarting PortAudio now would kill the playback
    tts.go.set()
    speaking.join(5)
    voice._mic = object()
    assert voice.headset_ready()
    assert sd.refreshes == 0
    voice._mic = None
    assert voice.headset_ready()
    assert sd.refreshes == 1


def test_no_audio_is_kept_by_default(tmp_path: Path) -> None:
    voice = MacVoice()
    assert voice._keep([0.0] * 1600, verdict="not speech") is None
    assert list(tmp_path.iterdir()) == []


def test_keep_audio_saves_each_clip_and_what_became_of_it(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")  # the voice group, on the Mac
    voice = MacVoice(keep_audio=tmp_path / "audio")
    name = voice._keep(np.zeros(1600, dtype=np.float32), verdict="speech", loudest=0.04)
    assert name is not None
    voice._keep(None, file=name, transcript="Yeah.", intent="approve")
    with wave.open(str(tmp_path / "audio" / name)) as clip:
        assert (clip.getframerate(), clip.getnframes()) == (16_000, 1600)
    lines = (tmp_path / "audio" / "clips.jsonl").read_text().splitlines()
    notes = [json.loads(line) for line in lines]
    assert [(n["file"], n.get("verdict"), n.get("transcript")) for n in notes] == [
        (name, "speech", None),
        (name, None, "Yeah."),
    ]


def loud_while_speaking(monkeypatch: pytest.MonkeyPatch, speech: bool) -> MacVoice:
    np = pytest.importorskip("numpy")  # the voice group, on the Mac
    voice = MacVoice()
    voice._mic_rate = mac.ASR_RATE
    voice._frames.append((time.monotonic(), np.full(320, 0.1, dtype=np.float32)))
    monkeypatch.setattr(voice, "is_speech", lambda clip: speech)
    voice._loud.set()  # what the mic callback does on a frame over BARGE_LEVEL
    return voice


def test_a_noise_while_speaking_doesnt_stop_earshot(monkeypatch: pytest.MonkeyPatch) -> None:
    voice = loud_while_speaking(monkeypatch, speech=False)
    assert not voice._talked_over()
    assert not voice._barge.is_set()
    assert voice._ignored == 1


def test_talking_over_earshot_stops_it(monkeypatch: pytest.MonkeyPatch) -> None:
    voice = loud_while_speaking(monkeypatch, speech=True)
    assert voice._talked_over()
    assert voice._talked_over()  # it stays stopped without asking Silero again
    assert voice._barge.is_set()


def test_the_listening_tone_is_short_soft_and_above_every_chime() -> None:
    tone = mac.listening_tone()
    assert len(tone) == int(mac.TTS_RATE * mac.LISTEN_TONE_S)
    assert max(abs(sample) for sample in tone) <= 0.15
    assert max(mac.CHIME_NOTES) * 1.25 < mac.LISTEN_TONE_HZ  # a chime's second note is 1.25x


def test_answers_are_scored_against_the_voiceprint_once_enrolled() -> None:
    from earshot.voice import voiceprint

    voice = MacVoice()
    assert not voice.speaker_ready()
    assert voice.speaker([0.0]) is None

    class Fixed:
        def __init__(self, vector: list[float]) -> None:
            self.vector = vector

        def embed(self, clip: object) -> list[float]:
            return self.vector

    voice._profile = voiceprint.build_profile([[1.0, 0.0]])
    voice._embedder = Fixed([1.0, 0.1])  # type: ignore[assignment]
    assert voice.speaker_ready()
    speaker = voice.speaker([0.0])
    assert speaker is not None
    assert speaker.verdict == "match"
    voice._embedder = Fixed([0.0, 1.0])  # type: ignore[assignment]
    assert voice.speaker([0.0]) == (0.0, "mismatch")


def test_the_helpers_chunks_become_frames_timed_by_their_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    np = pytest.importorskip("numpy")
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    voice = MacVoice()
    chunk = (np.ones(1600) * 3277).astype("<i2").tobytes()  # 100 ms, as the helper sends it
    voice._helper_audio(chunk)
    stamps = [t for t, _ in voice._frames]
    assert len(stamps) == 5  # 20 ms frames, as the endpointer was tuned on
    assert stamps == pytest.approx([99.92, 99.94, 99.96, 99.98, 100.0])
    assert all(len(frame) == 320 for _, frame in voice._frames)

    clock[0] = 100.13  # the next chunk arrives 30 ms late: its samples keep the time
    voice._helper_audio(chunk)
    assert [t for t, _ in voice._frames][5:] == pytest.approx(
        [100.02, 100.04, 100.06, 100.08, 100.1]
    )

    clock[0] = 100.15  # one that comes sooner than it says moves the clock back to the arrival
    voice._helper_audio(chunk)
    assert voice._frames[-1][0] == pytest.approx(100.15)

    clock[0] = 101.0  # after a gap, the clock starts again
    voice._helper_audio(chunk)
    assert voice._frames[-1][0] == pytest.approx(101.0)
    assert not voice._loud.is_set()  # Earshot wasn't speaking


def test_a_loud_helper_chunk_while_speaking_is_looked_at() -> None:
    np = pytest.importorskip("numpy")
    voice = MacVoice()
    voice._playing.set()
    quiet = np.zeros(1600, dtype="<i2")
    voice._helper_audio(quiet.tobytes())
    assert not voice._loud.is_set()
    quiet[320:640] = 8000  # one loud 20 ms frame in an otherwise quiet chunk
    voice._helper_audio(quiet.tobytes())
    assert voice._loud.is_set()
