"""§3.5 — on-device push-to-talk STT. Port of SpeechService.swift.

Backends:
- "windows": Windows.Media.SpeechRecognition (WinRT dictation, on-device when
  the speech language pack is installed) — the direct equivalent of
  SFSpeechRecognizer with requiresOnDeviceRecognition = true.
- "vosk": offline Vosk model (optional; set VOSK_MODEL_PATH or drop a model in
  %LOCALAPPDATA%\\Conductor\\vosk-model).

The partial/commit transcript merging is shared and mirrors Apple's behaviour
(segments finalise after pauses; the live partial is appended to committed).
"""

from __future__ import annotations

import math
import os
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Mic level meter (the pulsing dot): RMS of the input stream, throttled to 20 Hz.
# ---------------------------------------------------------------------------

class LevelMeter:
    def __init__(self) -> None:
        self.level = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.level = 0.0

    def _run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception:
            return
        last_publish = 0.0

        def callback(indata, frames, time_info, status):
            nonlocal last_publish
            try:
                rms = float(np.sqrt(np.mean(np.square(indata[:, 0])))) if frames else 0.0
                lv = min(1.0, rms * 12.0)
                self.level = self.level * 0.6 + lv * 0.4
            except Exception:
                pass

        try:
            with sd.InputStream(channels=1, samplerate=16000, blocksize=800, callback=callback):
                self._stop.wait()
        except Exception:
            pass
        self.level = 0.0


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class WindowsRecognizerBackend:
    """Continuous dictation via Windows.Media.SpeechRecognition (winsdk)."""

    name = "windows"

    def __init__(self, on_partial: Callable[[str], None], on_segment: Callable[[str], None],
                 on_error: Callable[[str], None]) -> None:
        self._on_partial = on_partial
        self._on_segment = on_segment
        self._on_error = on_error
        self._rec = None
        self._session = None
        self._handlers = []

    @staticmethod
    def available() -> bool:
        if not IS_WINDOWS:
            return False
        try:
            import winsdk.windows.media.speechrecognition  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> None:
        import asyncio

        try:
            from winsdk.windows.media.speechrecognition import (
                SpeechContinuousRecognitionSession, SpeechRecognizer,
                SpeechRecognitionTopicConstraint, SpeechRecognitionTopicType,
            )
        except Exception as e:
            self._on_error(f"Windows speech recognition unavailable: {e}")
            return

        async def boot():
            rec = SpeechRecognizer()
            constraint = SpeechRecognitionTopicConstraint(
                SpeechRecognitionTopicType.DICTATION, "dictation"
            )
            rec.constraints.append(constraint)
            compile_op = rec.compile_constraints_async()
            await compile_op
            return rec

        try:
            self._rec = asyncio.run(boot())
        except Exception as e:
            self._on_error(f"Speech recognizer init failed: {e}")
            return

        session = self._rec.continuous_recognition_session

        def on_hypothesis(_sender, args):
            try:
                text = args.result.text
                if text:
                    self._on_partial(text)
            except Exception:
                pass

        def on_result(_sender, args):
            try:
                text = args.result.text
                if text:
                    self._on_segment(text)
            except Exception:
                pass

        def on_completed(_sender, args):
            pass

        try:
            token_h = session.add_hypothesis_generated(on_hypothesis)
            token_r = session.add_result_generated(on_result)
            token_c = session.add_completed(on_completed)
            self._handlers = [(session, token_h), (session, token_r), (session, token_c)]
            asyncio.run(session.start_async())
        except Exception as e:
            self._on_error(f"Speech recognizer start failed: {e}")

    def stop(self) -> None:
        import asyncio

        if self._session is not None or self._rec is not None:
            try:
                session = self._rec.continuous_recognition_session if self._rec else None
                if session is not None:
                    asyncio.run(session.stop_async())
            except Exception:
                pass
        for session, token in self._handlers:
            try:
                session.remove_hypothesis_generated(token)
            except Exception:
                pass
            try:
                session.remove_result_generated(token)
            except Exception:
                pass
            try:
                session.remove_completed(token)
            except Exception:
                pass
        self._handlers = []
        self._rec = None


class VoskBackend:
    """Offline Vosk dictation fed from the mic via PortAudio."""

    name = "vosk"

    def __init__(self, on_partial: Callable[[str], None], on_segment: Callable[[str], None],
                 on_error: Callable[[str], None]) -> None:
        self._on_partial = on_partial
        self._on_segment = on_segment
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def model_path() -> Optional[str]:
        env = os.environ.get("VOSK_MODEL_PATH")
        if env and Path(env).is_dir():
            return env
        if IS_WINDOWS:
            local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            candidate = Path(local) / "Conductor" / "vosk-model"
            if candidate.is_dir():
                return str(candidate)
        return None

    @staticmethod
    def available() -> bool:
        if VoskBackend.model_path() is None:
            return False
        try:
            import vosk  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import json as _json

            import sounddevice as sd
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except Exception as e:
            self._on_error(f"Vosk unavailable: {e}")
            return
        SetLogLevel(-1)
        try:
            model = Model(self.model_path())
            rec = KaldiRecognizer(model, 16000)
        except Exception as e:
            self._on_error(f"Vosk model failed to load: {e}")
            return

        def callback(indata, frames, time_info, status):
            if self._stop.is_set():
                return
            try:
                if rec.AcceptWaveform(bytes(indata)):
                    obj = _json.loads(rec.Result())
                    text = (obj.get("text") or "").strip()
                    if text:
                        self._on_segment(text)
                else:
                    obj = _json.loads(rec.PartialResult())
                    text = (obj.get("partial") or "").strip()
                    if text:
                        self._on_partial(text)
            except Exception:
                pass

        try:
            with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                                   channels=1, callback=callback):
                self._stop.wait()
        except Exception as e:
            self._on_error(f"Microphone failed: {e}")


# ---------------------------------------------------------------------------
# Service facade — partial/commit merge identical to the Swift implementation.
# ---------------------------------------------------------------------------

class SpeechService:
    def __init__(self, backend: str = "auto") -> None:
        self.transcript = ""
        self.level = 0.0
        self.error: Optional[str] = None
        self.is_listening = False
        self._backend_name = backend
        self._backend = None
        self._meter = LevelMeter()
        self._last_partial = ""
        self._committed = ""
        self._lock = threading.RLock()
        self._final_event = threading.Event()
        self._final_text: Optional[str] = None

    # -- permission-ish checks -------------------------------------------

    @staticmethod
    def mic_available() -> bool:
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            return any(d.get("max_input_channels", 0) > 0 for d in devices)
        except Exception:
            return False

    @staticmethod
    def speech_available() -> bool:
        return WindowsRecognizerBackend.available() or VoskBackend.available()

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self.is_listening:
            return
        self.transcript = ""
        self._last_partial = ""
        self._committed = ""
        self.error = None
        self.level = 0.0

        if not self.mic_available():
            self.error = "No microphone input"
            return

        def on_partial(text: str) -> None:
            with self._lock:
                self._absorb(text)

        def on_segment(text: str) -> None:
            with self._lock:
                # The engine closed a segment mid-hold: bank it and keep listening.
                self._committed = _join(self._committed, text)
                self._last_partial = ""
                self.transcript = self._committed
                if not self.is_listening:
                    self._deliver_final()

        def on_error(msg: str) -> None:
            self.error = msg

        backend_name = self._backend_name
        order: list = []
        if backend_name in ("auto", "windows"):
            order.append(WindowsRecognizerBackend)
        if backend_name in ("auto", "vosk"):
            order.append(VoskBackend)

        self._backend = None
        errors = []
        for cls in order:
            if not cls.available():
                errors.append(f"{cls.name}: not available")
                continue
            self._backend = cls(on_partial, on_segment, on_error)
            break
        if self._backend is None:
            self.error = "Speech recognition unavailable — install the Windows speech pack or a Vosk model"
            return

        self.is_listening = True
        self._final_event = threading.Event()
        self._backend.start()
        self._meter.start()
        self._level_loop()

    def _level_loop(self) -> None:
        def loop():
            while self.is_listening:
                self.level = self._meter.level
                threading.Event().wait(0.05)
            self.level = 0.0
        threading.Thread(target=loop, daemon=True).start()

    def stop(self) -> str:
        """Stop capturing and wait (briefly) for the final transcript."""
        with self._lock:
            if not self.is_listening:
                return self.transcript
            self.is_listening = False
        if self._backend:
            self._backend.stop()
        self._meter.stop()
        # Never wait more than 1.2 s for the engine to finalise.
        self._final_event.wait(1.2)
        with self._lock:
            self._deliver_final()
            return _join(self._committed, self._last_partial)

    def cancel(self) -> None:
        with self._lock:
            self.is_listening = False
            self._committed = ""
            self._last_partial = ""
            self.transcript = ""
        if self._backend:
            self._backend.stop()
        self._meter.stop()
        self._final_event.set()

    # -- partial merge (port of absorb/commitPartial) --------------------

    def _absorb(self, text: str) -> None:
        if (self._last_partial and len(text) < len(self._last_partial) // 2
                and not self._last_partial.lower().startswith(text.lower()[:12])):
            self._commit_partial()
        self._last_partial = text
        self.transcript = _join(self._committed, text)

    def _commit_partial(self) -> None:
        self._committed = _join(self._committed, self._last_partial)
        self._last_partial = ""
        self.transcript = self._committed

    def _deliver_final(self) -> None:
        if self._final_text is None:
            self._final_text = _join(self._committed, self._last_partial)
        self._final_event.set()


def _join(a: str, b: str) -> str:
    b = (b or "").strip()
    a = (a or "").strip()
    if not a:
        return b
    if not b:
        return a
    return a + " " + b
