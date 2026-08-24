"""Individual TTS endpoint tests."""

import pytest
from config import TTS_BASE_URL, TTS_API_KEY, TEST_OUTPUT_DIR
from clients import TTSClient


@pytest.fixture
def tts():
    return TTSClient(TTS_BASE_URL, TTS_API_KEY)


def test_tts_english(tts):
    """Test TTS with English text."""
    out = TEST_OUTPUT_DIR / "tts_test_en.wav"
    result = tts.synthesize("Hello, welcome to Shunyalabs.", output_path=out)
    assert len(result.audio_bytes) > 1000, "Audio output too small, likely empty"
    assert out.exists()
    print(f"\n  Output: {out} ({len(result.audio_bytes)} bytes)")


def test_tts_hindi(tts):
    """Test TTS with Hindi text."""
    out = TEST_OUTPUT_DIR / "tts_test_hi.wav"
    result = tts.synthesize("नमस्कार, आप कैसे हैं?", output_path=out)
    assert len(result.audio_bytes) > 1000
    assert out.exists()
    print(f"\n  Output: {out} ({len(result.audio_bytes)} bytes)")


def test_tts_with_emotion_tag(tts):
    """Test TTS with emotion tag."""
    out = TEST_OUTPUT_DIR / "tts_test_emotion.wav"
    result = tts.synthesize("<Happy> This is a happy message!", output_path=out)
    assert len(result.audio_bytes) > 1000
    print(f"\n  Output: {out} ({len(result.audio_bytes)} bytes)")
