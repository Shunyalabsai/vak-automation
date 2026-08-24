"""Text translation client."""

import httpx
import time
from dataclasses import dataclass

# Map short language codes to full names expected by the new API
LANG_CODE_TO_NAME = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "or": "Odia",
    "as": "Assamese",
    "ur": "Urdu",
    "sa": "Sanskrit",
    "ne": "Nepali",
    "doi": "Dogri",
    "mai": "Maithili",
    "kok": "Konkani",
    "sd": "Sindhi",
    "ks": "Kashmiri",
    "mni": "Manipuri",
    "bo": "Bodo",
    "sat": "Santali",
}


def _lang_name(code: str) -> str:
    """Convert lang code to full name, pass through if already a name."""
    return LANG_CODE_TO_NAME.get(code.lower(), code)


@dataclass
class TranslateResult:
    translated_text: str
    source_lang: str
    target_lang: str
    processing_time_ms: float
    source_proxy: str | None
    target_proxy: str | None
    raw: dict


@dataclass
class LanguageInfo:
    code: str
    name: str
    lang_type: str


class TranslateClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = 3
        self.retry_backoff_seconds = 0.8

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslateResult:
        """Translate text between supported languages."""
        src_name = _lang_name(source_lang)
        tgt_name = _lang_name(target_lang)
        payload = {"text": text, "source_language": src_name, "target_language": tgt_name}
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }
        last_error: Exception | None = None
        resp = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = httpx.post(
                    f"{self.base_url}/v1/translate",
                    json=payload,
                    headers=headers,
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
                raise RuntimeError(f"Translate transient failure after retries: {e}") from e

        if resp is None:
            raise RuntimeError(f"Translate call failed: {last_error}")
        body = resp.json()

        inference_s = body.get("inference_time_s", 0)
        return TranslateResult(
            translated_text=body.get("translated_text", ""),
            source_lang=body.get("source_language", source_lang),
            target_lang=body.get("target_language", target_lang),
            processing_time_ms=round(inference_s * 1000, 2),
            source_proxy=None,
            target_proxy=None,
            raw=body,
        )

    def get_supported_languages(self) -> list[LanguageInfo]:
        """Fetch all supported languages."""
        resp = httpx.get(
            f"{self.base_url}/v1/languages",
            headers={"X-API-Key": self.api_key},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()

        langs = []
        for entry in body if isinstance(body, list) else body.get("languages", []):
            if isinstance(entry, str):
                langs.append(LanguageInfo(code=entry, name=entry, lang_type="native"))
            else:
                langs.append(LanguageInfo(
                    code=entry.get("code", entry.get("name", "")),
                    name=entry.get("name", ""),
                    lang_type=entry.get("type", "native")
                ))
        return langs
