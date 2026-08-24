"""ASR / Speech-to-Text client."""

import httpx
import time
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ASRResult:
    text: str
    language: str
    duration: float | None
    raw: dict


class ASRClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = 3
        self.retry_backoff_seconds = 1.0

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def transcribe(
        self,
        audio_path: str | Path,
        language_code: str = "Hindi",
        model: str = "zero-indic",
        response_format: str = "verbose_json",
        use_vad_chunking: bool = True,
        enable_profanity_hashing: bool = False,
    ) -> ASRResult:
        """Transcribe an audio file using the ASR endpoint."""
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        mime = "audio/wav" if audio_path.suffix in (".wav", ".wave") else f"audio/{audio_path.suffix.lstrip('.')}"

        data = {
            "enable_profanity_hashing": str(enable_profanity_hashing).lower(),
            "task": "transcribe",
            "model": model,
            "use_vad_chunking": str(use_vad_chunking).lower(),
            "language_code": language_code,
            "response_format": response_format,
        }
        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
        }

        last_error: Exception | None = None
        resp = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with open(audio_path, "rb") as f:
                    files = {"file": (audio_path.name, f, mime)}
                    resp = httpx.post(
                        f"{self.base_url}/v1/audio/transcriptions",
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=self.timeout,
                    )
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else None
                can_retry = bool(status and self._is_retryable_status(status))
                if can_retry and attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                raise RuntimeError(f"ASR transient failure after retries: {e}") from e

        if resp is None:
            raise RuntimeError(f"ASR call failed: {last_error}")
        body = resp.json()

        return ASRResult(
            text=body.get("text", ""),
            language=body.get("language", language_code),
            duration=body.get("duration"),
            raw=body,
        )
