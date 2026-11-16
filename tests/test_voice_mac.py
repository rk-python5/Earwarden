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
from earshot.voice.decider import CUT_OFF
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

    def __getitem__(self, index: Any) -> Any:
        return self if isinstance(index, slice) else super().__getitem__(index)

    def reshape(self, *shape: int) -> Clip:
        return self


class FakeStream:
    """An output stream: what's written, and whether it was drained or cut off."""

    def __init__(self, sd: FakeSounddevice) -> None:
        self.sd = sd

    def start(self) -> None:
        pass

    def write(self, data: Any) -> None:
        tag = getattr(data, "tag", None)
        self.sd.events.append(f"play {tag}" if tag else f"write {len(data)}")
        if self.sd.write_delay:
            time.sleep(self.sd.write_delay.pop(0))

    def stop(self) -> None:
        self.sd.events.append("drain")

    def abort(self) -> None:
        self.sd.events.append("abort")

    def close(self) -> None:
        pass


class FakeSounddevice(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("sounddevice")
        self.events: list[str] = []
        self.refreshes = 0
        self.write_delay: list[float] = []  # how long each write takes, in turn

    def OutputStream(self, **kwargs: Any) -> FakeStream:  # noqa: N802 - sounddevice's name
        return FakeStream(self)

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
    assert sd.events == ["play first 1", "abort", "play second 1", "play second 2", "drain"]


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


class InstantTTS:
    """Makes every clause at once, as Kokoro does for a short question (0.8 s for four).

    Clause n is n * 100 samples long, so the stream's writes show which clause played.
    """

    def __init__(self, clauses: int) -> None:
        self.clauses = clauses

    def generate(self, text: str, **kwargs: Any) -> Iterator[types.SimpleNamespace]:
        for n in range(1, self.clauses + 1):
            yield types.SimpleNamespace(audio=[0.0] * (n * 100))


@pytest.fixture
def stream_sd(monkeypatch: pytest.MonkeyPatch) -> FakeSounddevice:
    """A fake sounddevice with real numpy, for the tone."""
    fake = FakeSounddevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


def test_a_long_question_ends_even_when_its_clauses_fill_the_queue(
    stream_sd: FakeSounddevice,
) -> None:
    # Four clauses made at once fill the three-place queue while the first, long one plays.
    # The end marker used to give up after a second and be lost, and the speaker waited for it
    # until someone spoke or the request timed out (191 s at the Phase 4 gate).
    voice = MacVoice()
    voice._tts = InstantTTS(4)
    stream_sd.write_delay = [1.5]  # the first clause takes 1.5 s to play
    speaking = speak(voice, "q", threading.Event())
    speaking.join(6)
    assert not speaking.is_alive()
    assert stream_sd.events == ["write 100", "write 200", "write 300", "write 400", "drain"]


def test_a_question_ends_with_the_tone_on_the_same_stream(stream_sd: FakeSounddevice) -> None:
    voice = MacVoice()
    voice._tts = InstantTTS(2)
    voice._say("q", None, threading.Event(), True)
    tone = int(mac.TTS_RATE * mac.LISTEN_TONE_S)
    block = int(mac.TTS_RATE * mac.BLOCK_S)
    writes = [f"write {min(block, tone - n)}" for n in range(0, tone, block)]
    assert stream_sd.events == ["write 100", "write 200", *writes, "drain"]
    assert time.monotonic() - voice._toned < 1  # so the window opens without a second tone


def test_the_window_doesnt_play_the_tone_again_right_after_a_question(
    stream_sd: FakeSounddevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = MacVoice()
    voice._mic, voice._mic_rate = "mic", mac.ASR_RATE
    tones: list[float] = []
    monkeypatch.setattr(voice, "_tone", lambda: tones.append(time.monotonic()))
    voice._toned = time.monotonic()  # a question just ended with its tone
    assert voice._capture(0.05) is None
    assert tones == []
    assert voice._capture(0.05) is None  # push-to-talk later: no question, so its own tone
    assert len(tones) == 1


def test_talking_over_a_question_still_plays_the_tone_at_once(
    stream_sd: FakeSounddevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = MacVoice()
    voice._tts = InstantTTS(3)
    talked = iter([False, False, False, True])  # you start answering during the second clause
    monkeypatch.setattr(voice, "_talked_over", lambda: next(talked, True))
    voice._say("q", None, threading.Event(), True)
    tone = int(mac.TTS_RATE * mac.LISTEN_TONE_S)
    block = int(mac.TTS_RATE * mac.BLOCK_S)
    assert stream_sd.events[0] == "write 100"
    assert "write 300" not in stream_sd.events  # stopped for you
    assert stream_sd.events[-3:] == [f"write {block}", f"write {tone - block}", "drain"]
    assert time.monotonic() - voice._toned < 1


def test_a_cancelled_question_is_cut_off_without_a_tone(
    stream_sd: FakeSounddevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = MacVoice()
    voice._tts = InstantTTS(3)
    stop = threading.Event()
    checks = iter(range(100))

    def answered_on_screen() -> bool:  # during the second clause
        if next(checks) == 3:
            stop.set()
        return False

    monkeypatch.setattr(voice, "_talked_over", answered_on_screen)
    voice._say("q", None, stop, True)
    assert stream_sd.events[0] == "write 100"
    assert stream_sd.events[-1] == "abort"  # cut off at once, nothing more written
    assert "write 300" not in stream_sd.events
    assert voice._toned == 0.0


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


def test_a_nod_with_nods_off_is_seen_logged_and_ignored(caplog: pytest.LogCaptureFixture) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from test_gestures import still, swing

    class FakeHelper:
        connected = True
        on_audio: Any = None

        def __init__(self) -> None:
            self.motion = [*still(0, 1.5), *swing(1.5, "x"), *swing(2.1, "x"), *still(2.6, 1)]

    helper = FakeHelper()
    voice = MacVoice(helper=helper)  # type: ignore[arg-type]
    with caplog.at_level("INFO", logger="earshot.voice"):
        voice._nod_seen = False
        assert voice._gesture(0.0) is None  # nods are off (D-018): never a gesture
        assert voice._gesture(0.0) is None
    assert caplog.text.count("nod seen, ignored") == 1  # once per answer window
    assert MacVoice(helper=helper, nods=True)._gesture(0.0) == "nod"  # type: ignore[arg-type]
    helper.motion = [*still(0, 1.5), *swing(1.5, "z"), *swing(2.1, "z")]
    assert voice._gesture(0.0) == "shake"  # shakes always count


@pytest.mark.parametrize(("speech", "expected"), [(False, None), (True, "cut off")])
def test_only_speech_from_before_the_window_counts_as_cut_off(
    stream_sd: FakeSounddevice, monkeypatch: pytest.MonkeyPatch, speech: bool, expected: Any
) -> None:
    # A noise that the endpointer places before the window used to come back as "cut off", and
    # Earshot said "Wait for the tone" with nobody speaking. Speech still never gets parsed.
    import numpy as np

    from earshot.voice import endpoint

    voice = MacVoice()
    voice._mic, voice._mic_rate = "mic", mac.ASR_RATE
    voice._toned = time.monotonic()
    voice._frames.append((time.monotonic() + 60, np.full(320, 0.05, dtype=np.float32)))
    replies = iter([endpoint.Reply(0.0, 1e12, True, 0.001, 0.01, 0.05)])  # one sound, then quiet
    monkeypatch.setattr(endpoint, "find_reply", lambda *args: next(replies, None))
    monkeypatch.setattr(voice, "is_speech", lambda clip: speech)
    heard = voice._capture(0.05)
    assert heard is (CUT_OFF if expected == "cut off" else None)
