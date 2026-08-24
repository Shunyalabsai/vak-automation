"""Individual ASR endpoint tests."""

import pytest
from pathlib import Path
from config import ASR_BASE_URL, ASR_API_KEY, TEST_AUDIO_DIR
from clients import ASRClient


@pytest.fixture
def asr():
    return ASRClient(ASR_BASE_URL, ASR_API_KEY)


def get_audio_files():
    """Collect all audio files from test_audio/."""
    extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"}
    files = [f for f in TEST_AUDIO_DIR.iterdir() if f.suffix.lower() in extensions] if TEST_AUDIO_DIR.exists() else []
    if not files:
        pytest.skip("No audio files found in test_audio/")
    return files


@pytest.mark.parametrize("audio_file", get_audio_files() or [Path("skip")], ids=lambda f: f.name)
def test_asr_transcription(asr, audio_file):
    """Test that ASR returns a non-empty transcription for each audio file."""
    if not audio_file.exists():
        pytest.skip("No audio files")

    result = asr.transcribe(audio_file)

    assert result.text, f"Empty transcription for {audio_file.name}"
    assert isinstance(result.text, str)
    print(f"\n  File: {audio_file.name}")
    print(f"  Transcription: {result.text[:200]}")
    print(f"  Language: {result.language}")


def test_asr_returns_verbose_json(asr):
    """Test that verbose_json format returns expected fields."""
    files = get_audio_files()
    result = asr.transcribe(files[0], response_format="verbose_json")
    assert result.raw, "Raw response should not be empty"
    assert "text" in result.raw
