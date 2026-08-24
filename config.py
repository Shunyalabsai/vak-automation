"""Central configuration loaded from .env"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ASR / STT
ASR_BASE_URL = os.getenv("ASR_BASE_URL", "https://asr.shunyalabs.ai")
ASR_API_KEY = os.getenv("ASR_API_KEY", "")

# Translation
TRANSLATE_BASE_URL = os.getenv("TRANSLATE_BASE_URL", "https://genv3.uwc.world")
TRANSLATE_API_KEY = os.getenv("TRANSLATE_API_KEY", "")

# TTS
TTS_BASE_URL = os.getenv("TTS_BASE_URL", "https://tts.shunyalabs.ai")
TTS_API_KEY = os.getenv("TTS_API_KEY", "")

# Paths
PROJECT_ROOT = Path(__file__).parent
TEST_AUDIO_DIR = PROJECT_ROOT / "test_audio"
TEST_OUTPUT_DIR = PROJECT_ROOT / "test_output"
TEST_OUTPUT_DIR.mkdir(exist_ok=True)
