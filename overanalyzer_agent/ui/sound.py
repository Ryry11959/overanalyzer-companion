"""A tiny synthesized confirmation click - no bundled audio asset.

Playing a sound needs no network and no shipped binary: the shutter tick is a
few milliseconds of PCM synthesized on the fly and handed to the OS mixer
in-memory (``winsound.SND_MEMORY``). Two short sine blips with a fast
attack/decay envelope, so it reads as a soft camera-shutter click rather than a
beep. Windows-only; a no-op everywhere else, and a missed chime must never
interrupt capture, so every failure mode here is swallowed.
"""
from __future__ import annotations

import math
import struct
import sys

SAMPLE_RATE = 22050


def _tone(freq: float, ms: int, amplitude: float) -> bytes:
    """``ms`` of a sine at ``freq``, 16-bit mono PCM, with a click envelope."""
    n = int(SAMPLE_RATE * ms / 1000)
    if n <= 0:
        return b""
    out = bytearray()
    for i in range(n):
        t = i / SAMPLE_RATE
        # Fast attack, slower decay - reads as a click, not a sustained tone.
        envelope = min(1.0, i / max(1, n * 0.15)) * min(1.0, (n - i) / max(1, n * 0.5))
        sample = math.sin(2 * math.pi * freq * t) * amplitude * envelope if freq else 0.0
        out += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))
    return bytes(out)


def synthesize_shutter() -> bytes:
    """A soft two-tone confirmation click as an in-memory mono 16-bit WAV."""
    pcm = _tone(1050, 45, 0.35) + _tone(0, 15, 0.0) + _tone(1500, 55, 0.3)
    data_len = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_len, b"WAVE",
        b"fmt ", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16,
        b"data", data_len,
    )
    return header + pcm


_cached: bytes | None = None


def play_shutter() -> None:
    """Fire-and-forget the shutter chime. Never raises."""
    if sys.platform != "win32":
        return
    global _cached
    try:
        import winsound

        if _cached is None:
            _cached = synthesize_shutter()
        winsound.PlaySound(_cached, winsound.SND_MEMORY | winsound.SND_ASYNC)
    except Exception:  # noqa: BLE001 - audio must never break capture
        pass
