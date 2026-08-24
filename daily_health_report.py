#!/usr/bin/env python3
"""
Twice-daily consolidated health report for all automation projects.

Morning (~5:30 AM IST): latest run from today per project (after 4–5 AM batch).
Evening (~6:30 PM IST): latest run on each dashboard at report time (after 5–6 PM batch).

Run manually:
    python daily_health_report.py --period morning --preview
    python daily_health_report.py --period evening
    python daily_health_report.py --preview   # infers period from current IST hour

Environment:
    DIGEST_PERIOD  — morning | evening (optional; inferred from clock if unset)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import httpx

IST = timezone(timedelta(hours=5, minutes=30))

MORNING_RUN_START = time(4, 0)
MORNING_RUN_END = time(5, 59)
EVENING_RUN_START = time(17, 0)
EVENING_RUN_END = time(18, 59)

PROJECTS = [
    {
        "name": "Widget Automation",
        "dashboard": "https://shunyalabsai.github.io/widgets-automation/",
        "runs_url": "https://shunyalabsai.github.io/widgets-automation/history/runs.json",
        "format": "playwright",
    },
    {
        "name": "Console Automation",
        "dashboard": "https://shunyalabsai.github.io/console-automation/",
        "runs_url": "https://shunyalabsai.github.io/console-automation/history/runs.json",
        "format": "playwright",
    },
    {
        "name": "Asksam Automation",
        "dashboard": "https://shunyalabsai.github.io/asksam-automation/",
        "runs_url": "https://shunyalabsai.github.io/asksam-automation/history/runs.json",
        "format": "playwright",
    },
    {
        "name": "Vak BE Automation",
        "dashboard": "https://shunyalabsai.github.io/vak-automation/",
        "runs_url": "https://shunyalabsai.github.io/vak-automation/data.json",
        "format": "vak",
    },
]


def infer_period(now: datetime | None = None) -> str:
    """Infer morning vs evening from IST hour when period not specified."""
    now = now or datetime.now(IST)
    return "morning" if now.hour < 14 else "evening"


def parse_period(raw: str | None) -> str:
    if not raw:
        return infer_period()
    p = raw.strip().lower()
    if p in {"morning", "am", "morn"}:
        return "morning"
    if p in {"evening", "pm", "eve"}:
        return "evening"
    raise ValueError(f"Unknown period {raw!r}; use morning or evening")


def parse_iso_to_ist(ts: str) -> datetime | None:
    """Parse ISO timestamp into IST datetime."""
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif "IST" in ts:
            dt = datetime.strptime(ts.replace(" IST", ""), "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=IST)
        else:
            dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


def normalize_runs(raw, fmt: str) -> list[dict]:
    """Normalize project feeds into {timestamp, total, passed, failed, pass_rate, _dt}."""
    out: list[dict] = []
    if fmt == "playwright":
        for r in raw:
            summary = r.get("summary") or {}
            ts = r.get("startedAt") or r.get("runDate")
            total = summary.get("total", r.get("total", 0))
            passed = summary.get("passed", r.get("passed", 0))
            skipped = summary.get("skipped", r.get("skipped", 0))
            explicit_failed = summary.get("failed", r.get("failed", 0))
            timed_out = summary.get("timedOut", r.get("timedOut", 0))
            failed = max(total - passed - skipped, 0) if total else explicit_failed + timed_out
            dt = parse_iso_to_ist(ts or "")
            out.append({
                "timestamp": ts,
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": r.get("passRate", 0),
                "_dt": dt,
            })
    elif fmt == "vak":
        for r in raw.get("runs", []):
            ts = r.get("timestamp")
            dt = parse_iso_to_ist(ts or "")
            out.append({
                "timestamp": ts,
                "total": r.get("total", 0),
                "passed": r.get("passed", 0),
                "failed": r.get("failed", 0),
                "pass_rate": r.get("pass_rate", 0),
                "_dt": dt,
            })
    return [r for r in out if r.get("_dt")]


def run_in_window(dt: datetime, start: time, end: time) -> bool:
    t = dt.timetz().replace(tzinfo=None)
    return start <= t <= end


def pick_run_for_period(runs: list[dict], period: str, now: datetime) -> dict | None:
    """Select the run snapshot shown in the morning or evening digest."""
    if not runs:
        return None

    today = now.date()
    runs_today = [r for r in runs if r["_dt"].date() == today]
    runs_today.sort(key=lambda r: r["_dt"])

    if period == "morning":
        morning = [r for r in runs_today if run_in_window(r["_dt"], MORNING_RUN_START, MORNING_RUN_END)]
        if morning:
            return morning[-1]
        if runs_today:
            return runs_today[-1]
        return None

    # Evening: prefer latest run from today's evening window, else latest run today, else latest overall.
    evening = [r for r in runs_today if run_in_window(r["_dt"], EVENING_RUN_START, EVENING_RUN_END)]
    if evening:
        return evening[-1]

    if runs_today:
        return runs_today[-1]

    runs_sorted = sorted(runs, key=lambda r: r["_dt"])
    latest = runs_sorted[-1]
    if latest["_dt"].date() < today:
        return latest
    return latest


def describe_run_context(run: dict | None, period: str, now: datetime) -> str:
    """Human-readable note for why this run was chosen."""
    if run is None:
        if period == "morning":
            return "No run found yet today. Expected morning batch ~4:00–5:59 AM IST."
        return "No run found on dashboard. Expected evening batch ~5:00–6:59 PM IST."

    dt = run["_dt"]
    today = now.date()
    ts = dt.strftime("%I:%M %p IST")

    if period == "morning":
        if dt.date() < today:
            return f"No run yet today. Last available run was {dt.strftime('%b %d')} at {ts}."
        if run_in_window(dt, MORNING_RUN_START, MORNING_RUN_END):
            return f"Morning batch run at {ts}."
        return f"Latest run today at {ts} (outside usual 4–6 AM window)."

    if dt.date() < today:
        return f"No run today. Showing last available run from {dt.strftime('%b %d')} at {ts}."
    if run_in_window(dt, EVENING_RUN_START, EVENING_RUN_END):
        return f"Evening batch run at {ts}."
    if run_in_window(dt, MORNING_RUN_START, MORNING_RUN_END):
        return f"Evening batch not detected yet. Showing morning run at {ts}."
    return f"Latest run today at {ts}."


def fetch_project(project: dict) -> dict:
    try:
        r = httpx.get(project["runs_url"], timeout=15, follow_redirects=True)
        r.raise_for_status()
        runs = normalize_runs(r.json(), project["format"])
        return {"ok": True, "runs": runs, "error": ""}
    except Exception as e:
        return {"ok": False, "runs": [], "error": str(e)[:200]}


def build_project_section(project: dict, run: dict | None, note: str, fetch_error: str) -> dict:
    if fetch_error:
        return {
            "name": project["name"],
            "status": "ERROR",
            "last_run": "—",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0,
            "dashboard": project["dashboard"],
            "note": fetch_error,
        }
    if run is None:
        return {
            "name": project["name"],
            "status": "NO_RUN",
            "last_run": "No run found",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0,
            "dashboard": project["dashboard"],
            "note": note,
        }

    failed = run["failed"]
    pass_rate = run["pass_rate"]
    if not pass_rate and run["total"]:
        pass_rate = round(run["passed"] / run["total"] * 100, 1)

    if failed == 0 and run["total"] > 0:
        status = "GREEN"
    elif run["total"] == 0:
        status = "NO_DATA"
    else:
        status = "ISSUES"

    return {
        "name": project["name"],
        "status": status,
        "last_run": run["_dt"].strftime("%a %b %d, %I:%M %p IST"),
        "total": run["total"],
        "passed": run["passed"],
        "failed": failed,
        "pass_rate": pass_rate,
        "dashboard": project["dashboard"],
        "note": note,
    }


def period_meta(period: str, now: datetime) -> dict:
    if period == "morning":
        return {
            "label": "Morning Health Report",
            "subtitle": "Start-of-day snapshot — latest runs from today's morning batch (4–6 AM IST)",
            "subject_tag": "Morning",
            "icon": "🌅",
        }
    return {
        "label": "Evening Health Report",
        "subtitle": "End-of-day snapshot — latest run on each dashboard after the evening batch (5–7 PM IST)",
        "subject_tag": "Evening",
        "icon": "🌆",
    }


def render_html(sections: list[dict], period: str, now: datetime) -> tuple[str, str]:
    meta = period_meta(period, now)
    date_str = now.strftime("%a, %b %d, %Y")
    report_time = now.strftime("%I:%M %p IST")

    green = sum(1 for s in sections if s["status"] == "GREEN")
    issues = sum(1 for s in sections if s["status"] == "ISSUES")
    no_run = sum(1 for s in sections if s["status"] == "NO_RUN")
    errors = sum(1 for s in sections if s["status"] == "ERROR")

    overall_total = sum(s["total"] for s in sections if s["status"] in {"GREEN", "ISSUES", "NO_DATA"})
    overall_passed = sum(s["passed"] for s in sections if s["status"] in {"GREEN", "ISSUES", "NO_DATA"})
    overall_failed = sum(s["failed"] for s in sections if s["status"] in {"GREEN", "ISSUES", "NO_DATA"})
    overall_rate = round(overall_passed / overall_total * 100, 1) if overall_total else 0

    rows = ""
    for s in sections:
        if s["status"] == "ERROR":
            badge = '<span style="background:#fef2f2;color:#991b1b;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">FETCH ERROR</span>'
        elif s["status"] == "NO_RUN":
            badge = '<span style="background:#f3f4f6;color:#6b7280;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">NO RUN</span>'
        elif s["status"] == "GREEN":
            badge = '<span style="background:#dcfce7;color:#166534;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">ALL GREEN</span>'
        else:
            badge = '<span style="background:#fef2f2;color:#991b1b;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">ISSUES</span>'

        pass_cell = str(s["passed"]) if s["total"] else "—"
        fail_cell = (
            f'<span style="color:#ef4444;font-weight:700;">{s["failed"]}</span>'
            if s["failed"] > 0
            else (str(s["failed"]) if s["total"] else "—")
        )
        total_cell = str(s["total"]) if s["total"] else "—"
        rate_cell = f'{s["pass_rate"]}%' if s["total"] else "—"

        rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;font-size:13px;vertical-align:top;">
            <div style="font-weight:600;color:#333;">{s["name"]}</div>
            <a href="{s["dashboard"]}" style="font-size:11px;color:#7c3aed;text-decoration:none;">View Dashboard →</a>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;vertical-align:top;">{badge}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#333;vertical-align:top;">{s["last_run"]}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-size:13px;font-weight:600;vertical-align:top;">{total_cell}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;color:#22c55e;font-weight:600;font-size:13px;vertical-align:top;">{pass_cell}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-size:13px;vertical-align:top;">{fail_cell}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-size:13px;vertical-align:top;">{rate_cell}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#666;vertical-align:top;">{s["note"]}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:820px;margin:24px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:linear-gradient(135deg,#7c3aed,#a855f7);padding:28px 32px;color:#fff;">
      <div style="font-size:28px;margin-bottom:6px;">{meta["icon"]}</div>
      <h1 style="margin:0;font-size:24px;font-weight:700;">{meta["label"]}</h1>
      <p style="margin:6px 0 0;font-size:14px;opacity:0.9;">{meta["subtitle"]}</p>
      <p style="margin:8px 0 0;font-size:13px;opacity:0.85;">Report date: {date_str} · Generated at {report_time}</p>
    </div>

    <div style="padding:20px 32px;">
      <table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:separate;border-spacing:8px 8px;">
        <tr>
          <td width="20%" style="border:2px solid #dcfce7;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">All Green</div>
            <div style="font-size:22px;font-weight:700;color:#22c55e;margin-top:4px;">{green}</div>
          </td>
          <td width="20%" style="border:2px solid #fecaca;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">With Issues</div>
            <div style="font-size:22px;font-weight:700;color:#ef4444;margin-top:4px;">{issues}</div>
          </td>
          <td width="20%" style="border:2px solid #e5e7eb;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">No Run Yet</div>
            <div style="font-size:22px;font-weight:700;color:#6b7280;margin-top:4px;">{no_run}</div>
          </td>
          <td width="20%" style="border:2px solid #fef2f2;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Fetch Errors</div>
            <div style="font-size:22px;font-weight:700;color:#991b1b;margin-top:4px;">{errors}</div>
          </td>
          <td width="20%" style="border:2px solid #e5e7eb;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Pass Rate</div>
            <div style="font-size:22px;font-weight:700;color:{('#22c55e' if overall_rate >= 95 else '#f59e0b' if overall_rate >= 80 else '#ef4444')};margin-top:4px;">{overall_rate if overall_total else '—'}{'%' if overall_total else ''}</div>
          </td>
        </tr>
      </table>
      <p style="margin:14px 0 0;font-size:12px;color:#666;line-height:1.5;">
        Each row shows the <strong>latest relevant run</strong> for that project — not a full-day aggregate.
        If a scheduled batch has not finished yet, the note column explains what was found (or missing).
      </p>
    </div>

    <div style="margin:0 32px 24px;">
      <h3 style="font-size:16px;margin:0 0 12px 0;color:#333;">Project Status</h3>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:10px 16px;text-align:left;font-size:12px;font-weight:600;color:#666;">Project</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Status</th>
            <th style="padding:10px 16px;text-align:left;font-size:12px;font-weight:600;color:#666;">Last Run</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Tests</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Pass</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Fail</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Rate</th>
            <th style="padding:10px 16px;text-align:left;font-size:12px;font-weight:600;color:#666;">Note</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>

    <div style="border-top:1px solid #e5e7eb;padding:20px 32px;text-align:center;">
      <p style="margin:0;font-size:13px;color:#888;">Thanks &amp; Regards,</p>
      <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#333;">Saira Automation BOT</p>
    </div>
    <div style="background:#f9fafb;padding:8px;text-align:center;">
      <p style="margin:0;font-size:10px;color:#ccc;letter-spacing:1px;">CONFIDENTIAL COMMUNICATION</p>
    </div>
  </div>
</body></html>"""

    if issues > 0:
        subject = f"{meta['subject_tag']} QA Health Report – {date_str} – {issues} project(s) with issues"
    elif no_run > 0 or errors > 0:
        subject = f"{meta['subject_tag']} QA Health Report – {date_str} – {no_run} missing run(s), {errors} error(s)"
    elif green == len(sections) and overall_total:
        subject = f"{meta['subject_tag']} QA Health Report – {date_str} – All Green ({overall_rate}%)"
    else:
        subject = f"{meta['subject_tag']} QA Health Report – {date_str}"
    return html, subject


def send_email(html: str, subject: str) -> bool:
    url = os.environ.get("EMAIL_WEB_APP_URL", "")
    recipients = os.environ.get("EMAIL_RECIPIENTS", "")
    if not url or not recipients:
        print("EMAIL_WEB_APP_URL or EMAIL_RECIPIENTS not set.")
        return False
    payload = {"to": recipients, "subject": subject, "body": html}
    resp = httpx.post(url, json=payload, timeout=60, follow_redirects=True)
    if resp.status_code == 200:
        try:
            body = resp.json()
            if body.get("ok"):
                print(f"Digest sent to: {recipients}")
                return True
            print(f"Send failed: {body.get('error')}")
            return False
        except Exception:
            text = resp.text[:200]
            if "error" in text.lower():
                print(f"Send may have failed: {text}")
                return False
            print(f"Digest likely sent (non-JSON response). To: {recipients}")
            return True
    print(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return False


def main():
    preview = "--preview" in sys.argv
    period_arg = None
    for i, arg in enumerate(sys.argv):
        if arg == "--period" and i + 1 < len(sys.argv):
            period_arg = sys.argv[i + 1]
            break

    period = parse_period(period_arg or os.environ.get("DIGEST_PERIOD"))
    now = datetime.now(IST)

    sections = []
    for proj in PROJECTS:
        fetched = fetch_project(proj)
        if fetched["ok"]:
            run = pick_run_for_period(fetched["runs"], period, now)
            note = describe_run_context(run, period, now)
            sections.append(build_project_section(proj, run, note, ""))
        else:
            sections.append(build_project_section(proj, None, "", fetched["error"]))

    html, subject = render_html(sections, period, now)
    print(f"Period: {period}")
    print(f"Subject: {subject}")
    for s in sections:
        print(
            f"  {s['name']}: status={s['status']} last_run={s['last_run']} "
            f"pass={s['passed']} fail={s['failed']} | {s['note'][:80]}"
        )

    if preview:
        out = Path(__file__).parent / "digest_preview.html"
        out.write_text(html)
        print(f"Preview saved: {out}")
    else:
        send_email(html, subject)


if __name__ == "__main__":
    main()
