"""§3.7 — Fish Audio TTS over HTTPS (model s2.1-pro), queued playback,
barge-in, and a system-voice fallback so the app never goes silent.
Port of VoiceService.swift."""

from __future__ import annotations

import re
import threading
from typing import Callable, Optional

from ..core import securestore
from ..core.paths import AppLog

_BASE = "https://api.fish.audio"
MODEL = "s2.1-pro"          # "S2.1 Pro" — $15 / 1M chars of API credit
FREE_MODEL = "s2.1-pro-free"  # $0, verified working with zero API credit

_CUE_RE = re.compile(r"\s*\[[^\]]{1,30}\]\s*")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def strip_cues(text: str) -> str:
    """Fish Audio performs `[laughing]`-style cues; the system voice would
    read them literally, so drop them there."""
    s = _CUE_RE.sub(" ", text or "")
    s = _MULTI_SPACE_RE.sub(" ", s)
    return s.strip()


class FishAudioError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Fish {status}: {body[:120]}")


class FishAudio:
    """Fish Audio REST client. Verified against https://api.fish.audio/openapi.json."""

    @staticmethod
    def build_tts_body(text: str, voice_id: str, speed: float) -> dict:
        return {
            "text": text,
            "reference_id": voice_id,
            "format": "mp3",
            "mp3_bitrate": 128,
            "latency": "low",
            "normalize": True,
            "prosody": {"speed": speed, "volume": 0},
        }

    @staticmethod
    def _session():
        import requests
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        return s

    @staticmethod
    def synthesize(text: str, api_key: str, voice_id: str, speed: float,
                   model: str = MODEL) -> bytes:
        import requests

        url = f"{_BASE}/v1/tts"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": model,
        }
        body = FishAudio.build_tts_body(text, voice_id, speed)
        # Stale keep-alive sockets surface as connection errors and succeed on
        # retry (Fish makes the retry free).
        last_error: Exception = requests.RequestException("unknown")
        for attempt in range(3):
            try:
                resp = requests.post(url, json=body, headers=headers, timeout=(12, 20))
                if not (200 <= resp.status_code < 300):
                    raise FishAudioError(resp.status_code, resp.text or "")
                return resp.content
            except FishAudioError:
                raise
            except requests.RequestException as e:
                last_error = e
                if attempt < 2:
                    AppLog.write(f"fish tts retry {attempt + 1} after {e}")
                    threading.Event().wait(0.3)
        raise last_error

    @staticmethod
    def balance(api_key: str) -> dict:
        """Returns {balance, total, type, apiCreditUSD}.

        The HTTP API bills the separate "API credit" (USD), not the package
        credits — fetch both."""
        import requests

        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(f"{_BASE}/wallet/self/package", headers=headers, timeout=(12, 20))
        if resp.status_code != 200:
            raise FishAudioError(resp.status_code, resp.text or "")
        obj = resp.json()
        api = "?"
        try:
            r2 = requests.get(f"{_BASE}/wallet/self/api-credit", headers=headers, timeout=(12, 20))
            if r2.status_code == 200:
                api = str(r2.json().get("credit", "?"))
        except Exception:
            pass
        return {
            "balance": int(obj.get("balance", 0)) + int(obj.get("extra_balance", 0)),
            "total": obj.get("total", 0),
            "type": obj.get("type", ""),
            "apiCreditUSD": api,
        }

    @staticmethod
    def search_voices(api_key: str, query: str) -> list[dict]:
        """Returns [{id, title, tags}] — voices on the Fish marketplace."""
        import requests

        headers = {"Authorization": f"Bearer {api_key}"}
        params = {"page_size": "20", "language": "en"}
        if query:
            params["title"] = query
        resp = requests.get(f"{_BASE}/model", headers=headers, params=params, timeout=(12, 20))
        if resp.status_code != 200:
            raise FishAudioError(resp.status_code, resp.text or "")
        items = resp.json().get("items", [])
        out = []
        for i in items:
            if isinstance(i, dict) and i.get("_id") and i.get("title"):
                out.append({
                    "id": str(i["_id"]),
                    "title": str(i["title"]),
                    "tags": [str(t) for t in (i.get("tags") or [])][:3],
                })
        return out


class VoiceService:
    """Queued TTS with barge-in. Fish Audio first, system voice fallback."""

    def __init__(self, settings_store, on_finished: Optional[Callable[[], None]] = None) -> None:
        self._settings = settings_store
        self.on_finished = on_finished
        self.is_speaking = False
        self.last_mode = "fish"
        self.last_error: Optional[str] = None
        self._queue: list[str] = []
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._player = None
        self._pro_unavailable = False

    @property
    def has_fish_key(self) -> bool:
        return securestore.get(securestore.FISH_KEY) is not None

    def speak(self, text: str) -> None:
        t = (text or "").strip()
        if not t:
            return
        with self._lock:
            self._queue.append(t)
            if not self.is_speaking:
                self._play_next()

    def stop(self) -> None:
        """Barge-in: stop everything immediately."""
        with self._lock:
            self._queue.clear()
            self._cancel.set()
            if self._player is not None:
                try:
                    self._player.stop()
                except Exception:
                    pass
            was = self.is_speaking
            self.is_speaking = False
        if was and self.on_finished:
            try:
                self.on_finished()
            except Exception:
                pass

    def _play_next(self) -> None:
        with self._lock:
            if not self._queue:
                self.is_speaking = False
                finished = True
                text = None
            else:
                text = self._queue.pop(0)
                self.is_speaking = True
                self._cancel = threading.Event()
                finished = False
        if finished:
            if self.on_finished:
                try:
                    self.on_finished()
                except Exception:
                    pass
            return
        threading.Thread(target=self._speak_worker, args=(text, self._cancel), daemon=True).start()

    def _speak_worker(self, text: str, cancel: threading.Event) -> None:
        s = self._settings.settings
        key = securestore.get(securestore.FISH_KEY)
        if key:
            model = s.fishModel
            if model == "auto":
                model = FREE_MODEL if self._pro_unavailable else MODEL
            try:
                try:
                    data = FishAudio.synthesize(text, key, s.fishVoiceID, s.speakingRate, model)
                except FishAudioError as e:
                    if e.status == 402 and s.fishModel == "auto" and model != FREE_MODEL:
                        AppLog.write(f"fish: no API credit for {model} → using {FREE_MODEL}")
                        self._pro_unavailable = True
                        data = FishAudio.synthesize(text, key, s.fishVoiceID, s.speakingRate, FREE_MODEL)
                    else:
                        raise
                if cancel.is_set():
                    return
                self.last_mode = "fish"
                self.last_error = None
                self._play_audio(data, cancel)
                if not cancel.is_set():
                    self._play_next()
                return
            except Exception as e:
                self.last_error = str(e)
                AppLog.write(f"fish tts failed: {e}")
        else:
            AppLog.write("fish: no key readable → system voice")
        if cancel.is_set():
            return
        if s.systemVoiceFallback:
            self._speak_with_system(text, cancel)
        else:
            self._play_next()

    def _play_audio(self, data: bytes, cancel: threading.Event) -> None:
        from ..core.audio import Player

        player = Player()
        self._player = player

        def watcher():
            cancel.wait()
            player.stop()

        threading.Thread(target=watcher, daemon=True).start()
        try:
            player.play(data, "mp3")
        except Exception as e:
            self.last_error = f"playback: {e}"
            self._player = None
            raise

    def _speak_with_system(self, raw_text: str, cancel: threading.Event) -> None:
        from ..core.audio import speak_with_system, system_voice_available

        text = strip_cues(raw_text)
        self.last_mode = "system"
        if not text or not system_voice_available():
            self._play_next()
            return
        speak_with_system(text, self._settings.settings.speakingRate, stop_event=cancel)
        if not cancel.is_set():
            self._play_next()
