#!/usr/bin/env python3
"""
Vak API Test Runner

Usage:
    python run_tests.py                    # Run all tests
    python run_tests.py asr                # ASR tests only
    python run_tests.py translate          # Translation tests only
    python run_tests.py tts                # TTS tests only
    python run_tests.py pipeline           # End-to-end pipeline tests only
    python run_tests.py --quick            # One quick test per endpoint
"""

import sys
import subprocess


def main():
    args = sys.argv[1:]

    pytest_args = ["-v", "-s", "--tb=short"]

    if not args or args == ["all"]:
        pytest_args.append("tests/")
    elif args[0] == "asr":
        pytest_args.append("tests/test_asr.py")
    elif args[0] == "translate":
        pytest_args.append("tests/test_translate.py")
    elif args[0] == "tts":
        pytest_args.append("tests/test_tts.py")
    elif args[0] == "pipeline":
        pytest_args.append("tests/test_pipeline.py")
    elif args[0] == "--quick":
        pytest_args.extend([
            "tests/test_asr.py::test_asr_returns_verbose_json",
            "tests/test_translate.py::test_translate_en_to_hi",
            "tests/test_tts.py::test_tts_english",
        ])
    else:
        print(f"Unknown argument: {args[0]}")
        print("Usage: python run_tests.py [asr|translate|tts|pipeline|all|--quick]")
        sys.exit(1)

    sys.exit(subprocess.call(["python", "-m", "pytest"] + pytest_args))


if __name__ == "__main__":
    main()
