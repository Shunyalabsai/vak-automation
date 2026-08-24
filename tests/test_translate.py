"""Individual Translation endpoint tests."""

import pytest
from config import TRANSLATE_BASE_URL, TRANSLATE_API_KEY
from clients import TranslateClient


@pytest.fixture
def translator():
    return TranslateClient(TRANSLATE_BASE_URL, TRANSLATE_API_KEY)


def test_translate_en_to_hi(translator):
    """Test English to Hindi translation."""
    result = translator.translate("Hello, how are you?", "en", "hi")
    assert result.translated_text, "Translation should not be empty"
    assert result.source_lang == "en"
    assert result.target_lang == "hi"
    print(f"\n  EN → HI: {result.translated_text}")
    print(f"  Time: {result.processing_time_ms}ms")


def test_translate_hi_to_mr(translator):
    """Test Hindi to Marathi translation."""
    result = translator.translate("AC को २२ डिग्री पर सेट करो", "hi", "mr")
    assert result.translated_text, "Translation should not be empty"
    print(f"\n  HI → MR: {result.translated_text}")


def test_translate_hi_to_bn(translator):
    """Test Hindi to Bengali translation."""
    result = translator.translate("नमस्कार, आप कैसे हैं?", "hi", "bn")
    assert result.translated_text
    print(f"\n  HI → BN: {result.translated_text}")


def test_translate_proxied_language(translator):
    """Test translation to Dogri."""
    result = translator.translate("Hello, how are you?", "en", "doi")
    assert result.translated_text
    print(f"\n  EN → DOI: {result.translated_text}")


def test_supported_languages(translator):
    """Test that supported-languages endpoint returns languages."""
    langs = translator.get_supported_languages()
    assert len(langs) > 0, "Should return at least one language"
    names = [l.name.lower() for l in langs]
    assert any("english" in n for n in names)
    assert any("hindi" in n for n in names)
    print(f"\n  Total languages: {len(langs)}")
    print(f"  Sample: {[(l.code, l.name) for l in langs[:10]]}")
