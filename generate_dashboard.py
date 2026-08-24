#!/usr/bin/env python3
"""
Generate dashboard data (docs/data.json) from test results.

Accumulates run history so the dashboard shows trends over time.
Copies TTS audio to docs/audio/ for playback on GitHub Pages.
"""

import base64
import json
import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOCS_DIR = Path(__file__).parent / "docs"
AUDIO_DIR = DOCS_DIR / "audio"
DATA_FILE = DOCS_DIR / "data.json"
TEST_OUTPUT_DIR = Path(__file__).parent / "test_output"

RETENTION_DAYS = 30
IST = timezone(timedelta(hours=5, minutes=30))


def _parse_run_ts(ts: str) -> datetime | None:
    """Parse a run timestamp into an IST datetime. Returns None if unparseable."""
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
        if "IST" in ts:
            return datetime.strptime(ts.replace(" IST", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


def load_existing_data():
    """Load existing dashboard data (for run history)."""
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {"runs": [], "current": None}


def copy_audio_files(results: list[dict]) -> dict[str, str]:
    """Copy TTS output audio to docs/audio/, return filename->relative URL map."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_map = {}

    for r in results:
        fname = r.get("audio_filename", "")
        if not fname:
            continue

        # Try to copy from test_output
        src = TEST_OUTPUT_DIR / fname
        if src.exists():
            dst = AUDIO_DIR / fname
            shutil.copy2(src, dst)
            audio_map[fname] = f"audio/{fname}"

    return audio_map


def build_run_summary(results: list[dict], audio_map: dict[str, str]) -> dict:
    """Build a run summary from test results."""
    ts = results[0]["timestamp"] if results else datetime.now().isoformat()
    run_id = hashlib.md5(ts.encode()).hexdigest()[:8]

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)
    errors = sum(1 for r in results if r.get("error") and r["status"] == "FAIL")

    latencies = []
    for r in results:
        lat = r.get("latency_ms")
        if lat and lat != "":
            latencies.append(float(lat))

    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0
    total_ms = round(sum(latencies))

    # Build categories
    cat_map = {}
    for r in results:
        if r["test_type"] == "Pipeline":
            cat_name = "Pipeline"
        else:
            cat_name = r.get("endpoint", "Unknown")

        if cat_name not in cat_map:
            cat_map[cat_name] = {"tests": [], "pass": 0, "fail": 0, "error": 0, "latencies": []}

        cat_map[cat_name]["tests"].append(r)
        if r["status"] == "PASS":
            cat_map[cat_name]["pass"] += 1
        else:
            cat_map[cat_name]["fail"] += 1
            if r.get("error"):
                cat_map[cat_name]["error"] += 1

        lat = r.get("latency_ms")
        if lat and lat != "":
            cat_map[cat_name]["latencies"].append(float(lat))

    categories = []
    for name, data in cat_map.items():
        cat_total = data["pass"] + data["fail"]
        cat_lats = data["latencies"]
        categories.append({
            "name": name,
            "total": cat_total,
            "pass": data["pass"],
            "fail": data["fail"],
            "error": data["error"],
            "pass_rate": round(data["pass"] / cat_total * 100, 1) if cat_total > 0 else 0,
            "avg_latency": round(sum(cat_lats) / len(cat_lats)) if cat_lats else 0,
            "min_latency": round(min(cat_lats)) if cat_lats else 0,
            "max_latency": round(max(cat_lats)) if cat_lats else 0,
        })

    # Build test details
    tests = []
    failed_tests_meta = []
    for i, r in enumerate(results):
        lat = r.get("latency_ms", 0)
        if lat == "":
            lat = 0

        if r["test_type"] == "Pipeline":
            test_name = f"Pipeline {r.get('source_lang', '')}→{r.get('target_lang', '')}"
            category = "Pipeline"
            output_size = r.get("output_size", "")
            notes = ""
            if r.get("asr_text"):
                notes = f"ASR: {r['asr_text'][:80]}"
            # Prefer explicit output (includes API body on failure), else partial pipeline texts
            response = (r.get("output") or "").strip()
            if not response:
                parts = []
                if r.get("asr_text"):
                    parts.append(f"ASR: {r['asr_text'][:200]}")
                if r.get("translated_text"):
                    parts.append(f"Translate: {r['translated_text'][:200]}")
                response = " | ".join(parts)
        else:
            test_name = r.get("test_name", r.get("endpoint", ""))
            category = r.get("endpoint", "Unknown")
            output_size = r.get("output_size", "")
            notes = r.get("output", "")[:100] if r.get("output") else ""
            response = (r.get("output") or "").strip()

        # Parse output size to bytes
        size_bytes = 0
        if output_size and "bytes" in str(output_size):
            try:
                size_bytes = int(str(output_size).replace(" bytes", "").replace(",", ""))
            except ValueError:
                pass

        # Audio URL from copied files
        fname = r.get("audio_filename", "")
        audio_url = audio_map.get(fname, "")

        test_entry = {
            "id": f"T{i+1:03d}",
            "name": test_name,
            "category": category,
            "status": r["status"],
            "duration_ms": float(lat) if lat else 0,
            "audio_bytes": size_bytes,
            "output_format": "wav" if size_bytes > 0 else "-",
            "audio_url": audio_url,
            "error": r.get("error", ""),
            "notes": notes,
            "response": response[:500],
            "input": r.get("input", ""),
            "source_lang": r.get("source_lang", ""),
            "target_lang": r.get("target_lang", ""),
        }

        # Pipeline-specific latency breakdown
        if r["test_type"] == "Pipeline":
            test_entry["asr_latency_ms"] = r.get("asr_latency_ms", 0) or 0
            test_entry["translate_latency_ms"] = r.get("translate_latency_ms", 0) or 0
            test_entry["tts_latency_ms"] = r.get("tts_latency_ms", 0) or 0
            test_entry["asr_text"] = r.get("asr_text", "")
            test_entry["translated_text"] = r.get("translated_text", "")

        tests.append(test_entry)
        if r["status"] == "FAIL":
            failed_tests_meta.append({
                "id": test_entry["id"],
                "name": test_entry["name"],
                "category": test_entry["category"],
                "test_type": r.get("test_type", ""),
                "input": r.get("input", ""),
                "source_lang": r.get("source_lang", ""),
                "target_lang": r.get("target_lang", ""),
                "error": (r.get("error", "") or "")[:300],
                "response": (response or "")[:500],
            })

    return {
        "run_id": run_id,
        "timestamp": ts,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "avg_latency": avg_latency,
        "total_ms": total_ms,
        "categories": categories,
        "tests": tests,
        "failed_tests": failed_tests_meta,
    }


def generate_dashboard(results: list[dict]):
    """Generate docs/data.json from test results."""
    DOCS_DIR.mkdir(exist_ok=True)

    # Copy audio files to docs/audio/
    audio_map = copy_audio_files(results)

    existing = load_existing_data()
    run = build_run_summary(results, audio_map)

    # Add to history (keep last 100 runs for calendar)
    run_summary = {
        "run_id": run["run_id"],
        "timestamp": run["timestamp"],
        "total": run["total"],
        "passed": run["passed"],
        "failed": run["failed"],
        "pass_rate": run["pass_rate"],
        "avg_latency": run["avg_latency"],
        "failed_tests": run.get("failed_tests", []),
    }

    runs = existing.get("runs", [])
    # Avoid duplicate run_ids
    runs = [r for r in runs if r["run_id"] != run["run_id"]]
    runs.append(run_summary)

    # Keep runs from the last RETENTION_DAYS days (drop older entries).
    # Runs whose timestamp doesn't parse are kept defensively so we don't lose data.
    cutoff = datetime.now(IST) - timedelta(days=RETENTION_DAYS)
    runs = [r for r in runs if (_parse_run_ts(r.get("timestamp", "")) or cutoff) >= cutoff]

    data = {
        "current": run,
        "runs": runs,
    }

    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Dashboard data saved: {DATA_FILE}")
    if audio_map:
        print(f"Audio files copied: {len(audio_map)} files to docs/audio/")


if __name__ == "__main__":
    # Load latest report and generate
    report_path = Path(__file__).parent / "test_output" / "latest_report.json"
    if report_path.exists():
        results = json.loads(report_path.read_text())
        generate_dashboard(results)
    else:
        print("No latest_report.json found. Run report_to_sheet.py first.")
