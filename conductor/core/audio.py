"""Audio output: blip WAV, Fish Audio mp3 playback, system-voice fallback.

Everything is imported lazily so the logic stays testable on machines without
PortAudio (the Windows wheels bundle it).
"""

from __future__ import annotations

import io
import math
import struct
import threading
from typing import Optional


# ---------------------------------------------------------------------------
# Blip: 40 ms 880 Hz sine with a half-sine envelope, as 16-bit mono WAV
# (§5.5 — no bundled asset needed). Byte-identical to the macOS generator.
# ---------------------------------------------------------------------------

def blip_wav() -> bytes:
    sr = 44100
    n = int(0.04 * sr)
    pcm = bytearray()
    for i in range(n):
        env = math.sin(math.pi * i / n)
        v = int(12000 * math.sin(2 * math.pi * 880 * i / sr) * env)
        pcm += struct.pack("<h", v)
    out = bytearray()

    def u32(v: int) -> None:
        out.extend(struct.pack("<I", v))

    def u16(v: int) -> None:
        out.extend(struct.pack("<H", v))

    out.extend(b"RIFF")
    u32(36 + len(pcm))
    out.extend(b"WAVE")
    out.extend(b"fmt ")
    u32(16)
    u16(1)           # PCM
    u16(1)           # mono
    u32(sr)
    u32(sr * 2)      # byte rate
    u16(2)           # block align
    u16(16)          # bits
    out.extend(b"data")
    u32(len(pcm))
    out.extend(pcm)
    return bytes(out)


def play_blip(wav: bytes) -> None:
    """Best-effort one-shot playback of the down-chord blip."""
    if threading.current_thread() is not threading.main_thread():
        threading.Thread(target=play_blip, args=(wav,), daemon=True).start()
        return
    try:
        if _is_windows():
            import winsound
            winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_ASYNC)
            return
    except Exception:
        pass
    try:
        import sounddevice as sd
        import soundfile as sf
        data, rate = sf.read(io.BytesIO(wav), dtype="int16")
        sd.play(data, rate)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Blocking mp3 playback with barge-in (used by VoiceService).
# ---------------------------------------------------------------------------

class Player:
    """Plays audio bytes (mp3/wav) to the default output device; stop() barges in."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sd = None

    def play(self, data: bytes, fmt: str = "mp3") -> None:
        try:
            import sounddevice as sd
            import soundfile as sf
        except Exception:
            raise RuntimeError("audio output unavailable")
        self._sd = sd
        self._stop.clear()
        samples, rate = sf.read(io.BytesIO(data), dtype="float32")
        sd.play(samples, rate)
        try:
            while not self._stop.is_set():
                if not _stream_active(sd):
                    break
                self._stop.wait(0.05)
        finally:
            sd.stop()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._sd is not None:
                self._sd.stop()
        except Exception:
            pass


def _stream_active(sd) -> bool:
    try:
        stream = sd.get_stream()
        return bool(stream and stream.active)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# System voice fallback (SAPI5 on Windows via pyttsx3) — the port of
# AVSpeechSynthesizer. Fish Audio performs [laughing]-style cues; the system
# voice would read them literally, so drop them first (VoiceService.strip_cues).
# ---------------------------------------------------------------------------

def speak_with_system(text: str, rate: float = 1.0, stop_event: Optional[threading.Event] = None) -> None:
    if not text:
        return
    try:
        import pyttsx3
    except Exception:
        return
    try:
        engine = pyttsx3.init()
        # SAPI rate runs roughly -10…10; map the 0.7–1.4 multiplier onto it.
        engine.setProperty("rate", int(185 * rate))
        engine.say(text)
        if stop_event is not None:
            def watch():
                stop_event.wait()
                try:
                    engine.endLoop()
                except Exception:
                    pass
            threading.Thread(target=watch, daemon=True).start()
        engine.runAndWait()
        try:
            engine.stop()
        except Exception:
            pass
    except Exception:
        pass


def system_voice_available() -> bool:
    try:
        import pyttsx3  # noqa: F401
        return True
    except Exception:
        return False


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"
