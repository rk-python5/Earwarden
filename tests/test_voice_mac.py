"""The Mac voice's model cache check and audio locking, with sounddevice and numpy faked."""

from __future__ import annotations

import sys
import threading
import time
import types
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
