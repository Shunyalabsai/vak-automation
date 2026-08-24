"""End-to-end pipeline test: ASR → Translate → TTS (mirrors Vak website BE flow)."""

import pytest
from pathlib import Path
from config import (
    ASR_BASE_URL, ASR_API_KEY,
    TRANSLATE_BASE_URL, TRANSLATE_API_KEY,
    TTS_BASE_URL, TTS_API_KEY,
    TEST_AUDIO_DIR, TEST_OUTPUT_DIR,
)
from clients import ASRClient, TranslateClient, TTSClient


@pytest.fixture
def asr():
    return ASRClient(ASR_BASE_URL, ASR_API_KEY)


@pytest.fixture
def translator():
    return TranslateClient(TRANSLATE_BASE_URL, TRANSLATE_API_KEY)


@pytest.fixture
def tts():
    return TTSClient(TTS_BASE_URL, TTS_API_KEY)


def get_audio_files():
    extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"}
    files = [f for f in TEST_AUDIO_DIR.iterdir() if f.suffix.lower() in extensions] if TEST_AUDIO_DIR.exists() else []
    if not files:
        pytest.skip("No audio files in test_audio/")
    return files


# -------------------------------------------------------------------
# Pipeline configs: (source_language_for_asr, source_lang, target_lang)
# -------------------------------------------------------------------
PIPELINE_CONFIGS = [
    ("Hindi", "hi", "en"),
    ("Hindi", "hi", "mr"),
    ("Hindi", "hi", "bn"),
    ("Hindi", "hi", "ta"),
    ("Hindi", "hi", "te"),
]


@pytest.mark.parametrize(
    "asr_lang, src, tgt",
    PIPELINE_CONFIGS,
    ids=[f"{s}→{t}" for _, s, t in PIPELINE_CONFIGS],
)
def test_full_pipeline(asr, translator, tts, asr_lang, src, tgt):
    """
    Full Vak pipeline:
      1. ASR: audio → text (source language)
      2. Translate: source text → target text
      3. TTS: target text → audio
    """
    audio_files = get_audio_files()
    audio_file = audio_files[0]

    # --- Step 1: ASR ---
    print(f"\n  [ASR] Transcribing {audio_file.name} (lang={asr_lang})...")
    asr_result = asr.transcribe(audio_file, language_code=asr_lang)
    assert asr_result.text, "ASR returned empty transcription"
    print(f"  [ASR] Result: {asr_result.text[:200]}")

    # --- Step 2: Translate ---
    print(f"  [Translate] {src} → {tgt}...")
    translate_result = translator.translate(asr_result.text, src, tgt)
    assert translate_result.translated_text, "Translation returned empty"
    print(f"  [Translate] Result: {translate_result.translated_text[:200]}")
    print(f"  [Translate] Time: {translate_result.processing_time_ms}ms")

    # --- Step 3: TTS ---
    out_path = TEST_OUTPUT_DIR / f"pipeline_{src}_to_{tgt}_{audio_file.stem}.wav"
    print(f"  [TTS] Generating speech...")
    tts_result = tts.synthesize(translate_result.translated_text, output_path=out_path)
    assert len(tts_result.audio_bytes) > 1000, "TTS output too small"
    assert out_path.exists()
    print(f"  [TTS] Output: {out_path} ({len(tts_result.audio_bytes)} bytes)")
    print(f"  Pipeline complete: {audio_file.name} → [{asr_result.text[:50]}] → [{translate_result.translated_text[:50]}] → {out_path.name}")


def test_full_pipeline_all_audio_files(asr, translator, tts):
    """Run the hi→en pipeline for every audio file in test_audio/."""
    audio_files = get_audio_files()
    results = []

    for audio_file in audio_files:
        print(f"\n  --- Processing {audio_file.name} ---")

        asr_result = asr.transcribe(audio_file, language_code="Hindi")
        assert asr_result.text

        translate_result = translator.translate(asr_result.text, "hi", "en")
        assert translate_result.translated_text

        out_path = TEST_OUTPUT_DIR / f"pipeline_hi_en_{audio_file.stem}.wav"
        tts_result = tts.synthesize(translate_result.translated_text, output_path=out_path)
        assert len(tts_result.audio_bytes) > 1000

        results.append({
            "file": audio_file.name,
            "asr_text": asr_result.text,
            "translated_text": translate_result.translated_text,
            "tts_output": out_path.name,
            "tts_size": len(tts_result.audio_bytes),
        })

    print(f"\n  === Summary: {len(results)}/{len(audio_files)} files processed ===")
    for r in results:
        print(f"  {r['file']}: [{r['asr_text'][:60]}] → [{r['translated_text'][:60]}] → {r['tts_output']}")
