"""The synthesized shutter chime: a valid in-memory WAV, playable without raising."""
from overanalyzer_agent.ui import sound


def test_synthesize_shutter_is_a_valid_wav_header():
    data = sound.synthesize_shutter()
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    assert data[12:16] == b"fmt "
    assert data[36:40] == b"data"


def test_synthesize_shutter_is_short():
    """A confirmation click, not a jingle - comfortably under a fifth of a second."""
    data = sound.synthesize_shutter()
    data_len_declared = int.from_bytes(data[40:44], "little")
    duration_s = data_len_declared / 2 / sound.SAMPLE_RATE  # 16-bit mono
    assert 0 < duration_s < 0.2


def test_synthesize_shutter_is_deterministic():
    assert sound.synthesize_shutter() == sound.synthesize_shutter()


def test_play_shutter_never_raises(monkeypatch):
    monkeypatch.setattr(sound, "_cached", None)
    sound.play_shutter()  # no-op off Windows, or plays silently in CI


def test_play_shutter_swallows_a_broken_audio_backend(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sound, "_cached", None)

    class _BoomWinsound:
        SND_MEMORY = 0
        SND_ASYNC = 0

        @staticmethod
        def PlaySound(*_a, **_k):
            raise OSError("no audio device")

    monkeypatch.setitem(__import__("sys").modules, "winsound", _BoomWinsound)
    sound.play_shutter()  # must not raise
