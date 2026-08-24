"""TTS / Text-to-Speech client."""

import httpx
import time
from pathlib import Path
from dataclasses import dataclass


@dataclass
class TTSResult:
    audio_bytes: bytes
    output_path: Path | None
    content_type: str


class TTSClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = 3
        self.retry_backoff_seconds = 1.0

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def synthesize(
        self,
        text: str,
        language: str = "en",
        voice: str = "Rajesh",
        model: str = "zero-indic",
        response_format: str = "wav",
        output_path: str | Path | None = None,
    ) -> TTSResult:
        """Convert text to speech audio."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "input": text,
            "voice": voice,
            "model": model,
            "language": language,
            "response_format": response_format,
        }
        last_error: Exception | None = None
        resp = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = httpx.post(
                    f"{self.base_url}/v1/audio/speech",
                    headers=headers,
                    json=payload,
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
                raise RuntimeError(f"TTS transient failure after retries: {e}") from e

        if resp is None:
            raise RuntimeError(f"TTS call failed: {last_error}")

        final_resp = resp
        content = resp.content
        content_type = resp.headers.get("content-type", "")
        # If the response is not audio, parse the error body even on 200
        if "audio" not in content_type:
            try:
                err_body = resp.json()
                raise RuntimeError(f"TTS API returned non-audio response: {err_body}")
            except ValueError:
                raise RuntimeError(
                    f"TTS API returned non-audio response ({content_type}): "
                    f"{content[:300].decode(errors='replace')}"
                )
        # Transient empty/truncated bodies sometimes appear under load; retry a few times.
        undersized_attempts = 0
        max_undersized = 2
        while len(content) <= 1000 and undersized_attempts < max_undersized:
            undersized_attempts += 1
            time.sleep(self.retry_backoff_seconds * undersized_attempts)
            try:
                resp2 = httpx.post(
                    f"{self.base_url}/v1/audio/speech",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                resp2.raise_for_status()
                ct2 = resp2.headers.get("content-type", "")
                if "audio" not in ct2:
                    try:
                        err_body = resp2.json()
                        raise RuntimeError(f"TTS retry returned non-audio: {err_body}")
                    except ValueError:
                        raise RuntimeError(
                            f"TTS retry returned non-audio ({ct2}): "
                            f"{resp2.content[:300].decode(errors='replace')}"
                        )
                final_resp = resp2
                content = resp2.content
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                raise RuntimeError(
                    f"TTS undersized retry failed ({len(content)} bytes): {e}"
                ) from e

        saved_path = None
        if output_path:
            saved_path = Path(output_path)
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_bytes(content)

        return TTSResult(
            audio_bytes=content,
            output_path=saved_path,
            content_type=final_resp.headers.get("content-type", ""),
        )
