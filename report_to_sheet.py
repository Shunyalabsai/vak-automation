#!/usr/bin/env python3
"""
Run all tests and push results to Google Sheets via Apps Script Web App.

Usage:
    python report_to_sheet.py                  # Run all tests & push
    python report_to_sheet.py --dry-run        # Run tests, print report, don't push
"""

import base64
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from config import (
    ASR_BASE_URL, ASR_API_KEY,
    TRANSLATE_BASE_URL, TRANSLATE_API_KEY,
    TTS_BASE_URL, TTS_API_KEY,
    TEST_AUDIO_DIR, TEST_OUTPUT_DIR,
)
from clients import ASRClient, TranslateClient, TTSClient
from generate_dashboard import generate_dashboard

# ── Google Apps Script Web App URL ──
# After deploying the Apps Script, paste the URL here:
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxhP5uUl48vWntyM8K7djZPqNwW32UcwbjPK5iNHItr_N6c8qoUP76dZaCMd3THn62Cbw/exec"

IST = timezone(timedelta(hours=5, minutes=30))

# Many schedulers (including sister automations) fire at xx:58 IST, causing API bursts.
# Spread CI starts so this repo does not align exactly with that minute.
def _in_xx58_collision_window(now: datetime) -> bool:
    """True around :56–:01 each hour when jobs aligned to :58 start or finish."""
    m = now.minute
    return m >= 56 or m <= 1


def _ci_load_spread_delay_sec() -> float:
    """Optional delay before any API calls when running in GitHub Actions."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return 0.0
    override = os.environ.get("VAK_STAGGER_SEC")
    if override is not None and override.strip() != "":
        try:
            return max(0.0, float(override))
        except ValueError:
            pass
    now = datetime.now(IST)
    in_peak_window = _in_xx58_collision_window(now)
    rid = os.environ.get("GITHUB_RUN_ID", "0")
    try:
        salt = int(rid) % 90
    except ValueError:
        salt = 42
    if in_peak_window:
        # Stronger spread during the common :58 IST collision window.
        return 45.0 + float(salt)  # ~45–134s
    return 12.0 + float(salt % 48)  # ~12–59s otherwise


def timestamp():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def _response_from_exception(exc: Exception) -> str:
    """Best-effort capture of API response body when a call fails."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        try:
            text = exc.response.text.strip()
            if text:
                return text[:500]
        except Exception:
            pass
        return f"HTTP {exc.response.status_code}"
    msg = str(exc).strip()
    return msg[:500] if msg else ""


def run_individual_tests():
    """Run individual endpoint tests, return list of result dicts."""
    results = []
    run_ts = timestamp()

    # ── ASR Tests ──
    asr = ASRClient(ASR_BASE_URL, ASR_API_KEY)
    audio_files = []
    extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"}
    if TEST_AUDIO_DIR.exists():
        audio_files = sorted(f for f in TEST_AUDIO_DIR.iterdir() if f.suffix.lower() in extensions)

    for audio_file in audio_files:
        row = {
            "timestamp": run_ts,
            "test_type": "Individual",
            "endpoint": "ASR",
            "test_name": f"ASR - {audio_file.name}",
            "input": audio_file.name,
            "source_lang": "Hindi",
            "target_lang": "-",
            "output": "",
            "status": "",
            "latency_ms": "",
            "output_size": "",
            "error": "",
        }
        try:
            t0 = time.time()
            r = asr.transcribe(audio_file, language_code="Hindi")
            latency = round((time.time() - t0) * 1000, 1)
            row["output"] = r.text[:500]
            row["status"] = "PASS" if r.text else "FAIL"
            row["latency_ms"] = latency
            if not r.text:
                row["error"] = "ASR returned empty transcription"
                row["output"] = "(empty transcription)"
        except Exception as e:
            row["status"] = "FAIL"
            row["error"] = str(e)[:300]
            row["output"] = _response_from_exception(e)
        results.append(row)

    # ── Translate Tests ──
    translator = TranslateClient(TRANSLATE_BASE_URL, TRANSLATE_API_KEY)
    translate_cases = [
        ("Hello, how are you?", "en", "hi"),
        ("AC को २२ डिग्री पर सेट करो", "hi", "mr"),
        ("नमस्कार, आप कैसे हैं?", "hi", "bn"),
        ("Hello, how are you?", "en", "doi"),  # proxied
        ("Hello, how are you?", "en", "ta"),
        ("Hello, how are you?", "en", "te"),
    ]
    for text, src, tgt in translate_cases:
        row = {
            "timestamp": run_ts,
            "test_type": "Individual",
            "endpoint": "Translate",
            "test_name": f"Translate {src}→{tgt}",
            "input": text[:100],
            "source_lang": src,
            "target_lang": tgt,
            "output": "",
            "status": "",
            "latency_ms": "",
            "output_size": "",
            "error": "",
        }
        try:
            r = translator.translate(text, src, tgt)
            row["output"] = r.translated_text[:500]
            row["status"] = "PASS" if r.translated_text else "FAIL"
            row["latency_ms"] = r.processing_time_ms
            if not r.translated_text:
                row["error"] = "Translation returned empty result"
                row["output"] = "(empty translation)"
            elif r.target_proxy:
                row["error"] = f"Proxy: {r.target_proxy[:200]}"
        except Exception as e:
            row["status"] = "FAIL"
            row["error"] = str(e)[:300]
            row["output"] = _response_from_exception(e)
        results.append(row)

    # ── Supported Languages (health check) ──
    row = {
        "timestamp": run_ts,
        "test_type": "Individual",
        "endpoint": "Translate",
        "test_name": "Supported Languages",
        "input": "GET /health",
        "source_lang": "-",
        "target_lang": "-",
        "output": "",
        "status": "",
        "latency_ms": "",
        "output_size": "",
        "error": "",
    }
    try:
        import httpx as _httpx
        t0 = time.time()
        resp = _httpx.get(f"{TRANSLATE_BASE_URL}/health", headers={"X-API-Key": TRANSLATE_API_KEY}, timeout=15)
        latency = round((time.time() - t0) * 1000, 1)
        resp.raise_for_status()
        body = resp.json()
        row["output"] = str(body)
        row["status"] = "PASS" if body.get("translate_loaded") else "FAIL"
        row["latency_ms"] = latency
        if not body.get("translate_loaded"):
            row["error"] = "translate_loaded is false"
            row["output"] = str(body)[:500]
    except Exception as e:
        row["status"] = "FAIL"
        row["error"] = str(e)[:300]
        row["output"] = _response_from_exception(e)
    results.append(row)

    # ── TTS Tests ──
    tts = TTSClient(TTS_BASE_URL, TTS_API_KEY)
    tts_cases = [
        ("Hello, welcome to Shunyalabs.", "en", "Rajesh", "tts_report_en.wav"),
        ("नमस्कार, आप कैसे हैं?", "hi", "Rajesh", "tts_report_hi.wav"),
        ("<Happy> This is a happy message!", "en", "Rajesh", "tts_report_emotion.wav"),
    ]
    for text, lang, voice, fname in tts_cases:
        out_path = TEST_OUTPUT_DIR / fname
        row = {
            "timestamp": run_ts,
            "test_type": "Individual",
            "endpoint": "TTS",
            "test_name": f"TTS - {fname}",
            "input": text[:100],
            "source_lang": "-",
            "target_lang": "-",
            "output": str(out_path.name),
            "status": "",
            "latency_ms": "",
            "output_size": "",
            "error": "",
            "audio_b64": "",
            "audio_filename": fname,
        }
        try:
            t0 = time.time()
            r = tts.synthesize(text, language=lang, voice=voice, output_path=out_path)
            latency = round((time.time() - t0) * 1000, 1)
            row["status"] = "PASS" if len(r.audio_bytes) > 1000 else "FAIL"
            row["latency_ms"] = latency
            row["output_size"] = f"{len(r.audio_bytes)} bytes"
            row["audio_b64"] = base64.b64encode(r.audio_bytes).decode("ascii")
            if len(r.audio_bytes) <= 1000:
                row["error"] = f"TTS output too small ({len(r.audio_bytes)} bytes)"
                row["output"] = f"{len(r.audio_bytes)} bytes received"
        except Exception as e:
            row["status"] = "FAIL"
            row["error"] = str(e)[:300]
            row["output"] = _response_from_exception(e)
        results.append(row)

    return results


def run_pipeline_tests():
    """Run end-to-end pipeline tests, return list of result dicts."""
    results = []
    run_ts = timestamp()

    asr = ASRClient(ASR_BASE_URL, ASR_API_KEY)
    translator = TranslateClient(TRANSLATE_BASE_URL, TRANSLATE_API_KEY)
    tts = TTSClient(TTS_BASE_URL, TTS_API_KEY)

    extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"}
    audio_files = []
    if TEST_AUDIO_DIR.exists():
        audio_files = sorted(f for f in TEST_AUDIO_DIR.iterdir() if f.suffix.lower() in extensions)

    if not audio_files:
        return results

    pipeline_configs = [
        ("Hindi", "hi", "en"),
        ("Hindi", "hi", "mr"),
        ("Hindi", "hi", "bn"),
        ("Hindi", "hi", "ta"),
        ("Hindi", "hi", "te"),
    ]

    for audio_file in audio_files:
        for asr_lang, src, tgt in pipeline_configs:
            row = {
                "timestamp": run_ts,
                "test_type": "Pipeline",
                "endpoint": "ASR→Translate→TTS",
                "input": audio_file.name,
                "source_lang": src,
                "target_lang": tgt,
                "asr_text": "",
                "translated_text": "",
                "tts_file": "",
                "status": "",
                "asr_latency_ms": "",
                "translate_latency_ms": "",
                "tts_latency_ms": "",
                "latency_ms": "",
                "output_size": "",
                "error": "",
                "audio_b64": "",
                "audio_filename": "",
            }

            total_t0 = time.time()
            try:
                # Step 1: ASR
                t1 = time.time()
                asr_result = asr.transcribe(audio_file, language_code=asr_lang)
                row["asr_latency_ms"] = round((time.time() - t1) * 1000, 1)
                if not asr_result.text:
                    raise ValueError("ASR returned empty text")
                row["asr_text"] = asr_result.text[:500]

                # Step 2: Translate
                t2 = time.time()
                tr_result = translator.translate(asr_result.text, src, tgt)
                row["translate_latency_ms"] = round((time.time() - t2) * 1000, 1)
                if not tr_result.translated_text:
                    raise ValueError("Translation returned empty text")
                row["translated_text"] = tr_result.translated_text[:500]

                # Brief pause before TTS — reduces burst load when many jobs hit APIs at :58 IST.
                time.sleep(1.5)

                # Step 3: TTS
                out_path = TEST_OUTPUT_DIR / f"pipeline_{src}_{tgt}_{audio_file.stem}.wav"
                t3 = time.time()
                tts_result = tts.synthesize(tr_result.translated_text, language=tgt, output_path=out_path)
                row["tts_latency_ms"] = round((time.time() - t3) * 1000, 1)

                total_latency = round((time.time() - total_t0) * 1000, 1)

                row["tts_file"] = out_path.name
                row["status"] = "PASS" if len(tts_result.audio_bytes) > 1000 else "FAIL"
                row["latency_ms"] = total_latency
                row["output_size"] = f"{len(tts_result.audio_bytes)} bytes"
                row["audio_b64"] = base64.b64encode(tts_result.audio_bytes).decode("ascii")
                row["audio_filename"] = out_path.name
                if len(tts_result.audio_bytes) <= 1000:
                    row["error"] = f"Pipeline TTS output too small ({len(tts_result.audio_bytes)} bytes)"
                    row["output"] = f"{len(tts_result.audio_bytes)} bytes received"

            except Exception as e:
                total_latency = round((time.time() - total_t0) * 1000, 1)
                row["status"] = "FAIL"
                row["latency_ms"] = total_latency
                row["error"] = str(e)[:300]
                # Keep any partial pipeline outputs + API body for dashboard proof
                parts = []
                if row.get("asr_text"):
                    parts.append(f"ASR: {row['asr_text'][:200]}")
                if row.get("translated_text"):
                    parts.append(f"Translate: {row['translated_text'][:200]}")
                api_body = _response_from_exception(e)
                if api_body and api_body not in (row.get("error") or ""):
                    parts.append(f"API: {api_body[:250]}")
                row["output"] = " | ".join(parts) if parts else api_body

            results.append(row)
            # Space out pipeline legs so ASR/TTS are not back-to-back during peak windows.
            time.sleep(2.0)

    return results


def push_to_sheet(results: list[dict]):
    """Send results to Google Sheets via Apps Script Web App."""
    if not APPS_SCRIPT_URL:
        print("\n⚠  APPS_SCRIPT_URL not set in report_to_sheet.py")
        print("   Deploy the Apps Script and paste the URL to enable auto-reporting.")
        return False

    payload = {"results": results, "script_url": APPS_SCRIPT_URL}
    try:
        resp = httpx.post(APPS_SCRIPT_URL, json=payload, timeout=120, follow_redirects=True)
    except Exception as e:
        print(f"\nFailed to push to sheet (network): {e}")
        return False
    if resp.status_code == 200:
        print(f"\nPushed {len(results)} rows to Google Sheet.")
        return True
    print(f"\nFailed to push to sheet: {resp.status_code} {resp.text[:200]}")
    return False


def print_report(results: list[dict]):
    """Print a summary table."""
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")

    print("\n" + "=" * 90)
    print(f"  VAK API TEST REPORT  |  {results[0]['timestamp'] if results else 'N/A'}")
    print(f"  Total: {len(results)}  |  Passed: {passed}  |  Failed: {failed}")
    print("=" * 90)

    print(f"\n{'Status':<8} {'Type':<12} {'Test Name':<45} {'Latency':<12}")
    print("-" * 80)
    for r in results:
        lat = f"{r['latency_ms']}ms" if r['latency_ms'] else "-"
        status_marker = "PASS" if r["status"] == "PASS" else "FAIL"
        if r["test_type"] == "Pipeline":
            name = f"Pipeline {r['input']} ({r['source_lang']}→{r['target_lang']})"
        else:
            name = r.get("test_name", r.get("endpoint", ""))
        print(f"{status_marker:<8} {r['test_type']:<12} {name:<45} {lat:<12}")
        if r.get("error") and "Proxy" not in r["error"]:
            print(f"         Error: {r['error'][:70]}")

    print()


def _persist_results(all_results: list[dict]) -> None:
    """Save report + dashboard data — must run even if sheet/git push fails."""
    report_path = TEST_OUTPUT_DIR / "latest_report.json"
    report_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"Local report saved: {report_path}")
    generate_dashboard(all_results)


def main():
    dry_run = "--dry-run" in sys.argv
    all_results: list[dict] = []

    try:
        delay = _ci_load_spread_delay_sec()
        if delay > 0:
            print(f"Load spread: waiting {delay:.0f}s before API tests (avoids xx:IST collision bursts)...")
            time.sleep(delay)

        print("Running individual endpoint tests...")
        individual = run_individual_tests()

        print("Running pipeline tests...")
        pipeline = run_pipeline_tests()

        all_results = individual + pipeline
        print_report(all_results)

        # Persist first so CI can commit dashboard + send email even if sheet push fails.
        _persist_results(all_results)

        if not dry_run:
            push_to_sheet(all_results)
            # CI workflow commits docs/ — avoid double-push race with the Actions git step.
            if os.environ.get("GITHUB_ACTIONS") != "true":
                push_dashboard()
        else:
            print("[Dry run - skipping Google Sheets push]")
    except Exception:
        if all_results:
            print("\n⚠  Run interrupted after partial results — saving dashboard anyway.")
            _persist_results(all_results)
        traceback.print_exc()
        sys.exit(1)

    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    if failed:
        print(f"\n{failed} test(s) failed — CI will mark this run as failed.")
        sys.exit(1)


def push_dashboard():
    """Auto-commit and push docs/ to GitHub so dashboard updates."""
    try:
        repo_root = Path(__file__).parent
        subprocess.run(["git", "add", "docs/"], cwd=repo_root, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "status", "--porcelain", "docs/"],
            cwd=repo_root, capture_output=True, text=True,
        )
        if not result.stdout.strip():
            print("Dashboard: no changes to push.")
            return
        ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
        subprocess.run(
            ["git", "commit", "-m", f"Auto-update dashboard ({ts})"],
            cwd=repo_root, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=repo_root, check=True, capture_output=True, timeout=30,
        )
        print("Dashboard pushed to GitHub Pages.")
    except Exception as e:
        print(f"Dashboard push failed: {e}")


if __name__ == "__main__":
    main()
