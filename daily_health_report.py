#!/usr/bin/env python3
"""
Daily consolidated health report for all automation projects.

Fetches yesterday's test runs from each project's GitHub Pages dashboard,
builds one HTML email summary, and sends via the email Apps Script.

Run manually:
    python daily_health_report.py            # Send email
    python daily_health_report.py --preview  # Save HTML to digest_preview.html
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

IST = timezone(timedelta(hours=5, minutes=30))

PROJECTS = [
    {
        "name": "Asksam Automation",
        "dashboard": "https://saira-uwc.github.io/asksam-datascience-automation/",
        "runs_url": "https://saira-uwc.github.io/asksam-datascience-automation/history/runs.json",
        "format": "playwright",
    },
    {
        "name": "Website Automation",
        "dashboard": "https://saira-uwc.github.io/Shunyalabs_website/",
        "runs_url": "https://saira-uwc.github.io/Shunyalabs_website/history/runs.json",
        "format": "playwright",
    },
    {
        "name": "Widget Automation",
        "dashboard": "https://saira-uwc.github.io/Shunyalabs_widget/",
        "runs_url": "https://saira-uwc.github.io/Shunyalabs_widget/history/runs.json",
        "format": "playwright",
    },
    {
        "name": "Console Dashboard",
        "dashboard": "https://saira-uwc.github.io/Shunyalabs_console/",
        "runs_url": "https://saira-uwc.github.io/Shunyalabs_console/history/runs.json",
        "format": "playwright",
    },
    {
        "name": "Vak BE Automation",
        "dashboard": "https://shunyalabsai.github.io/vak-automation/",
        "runs_url": "https://shunyalabsai.github.io/vak-automation/data.json",
        "format": "vak",
    },
    # Temporarily hidden — dashboards returning 404
    # {
    #     "name": "Concurrent (Zero Indic)",
    #     "dashboard": "https://yamini-pal-singh.github.io/automation-testing/Concurrent-Report.html",
    #     "runs_url": "https://yamini-pal-singh.github.io/automation-testing/concurrent-runs.json",
    #     "format": "playwright",
    # },
    # {
    #     "name": "Long Audio (Zero Indic)",
    #     "dashboard": "https://yamini-pal-singh.github.io/automation-testing/Long-Audio-Report.html",
    #     "runs_url": "https://yamini-pal-singh.github.io/automation-testing/long-audio-runs.json",
    #     "format": "playwright",
    # },
    # {
    #     "name": "Playground",
    #     "dashboard": "https://yamini-pal-singh.github.io/playground-testing/Playground-Report.html",
    #     "runs_url": "https://yamini-pal-singh.github.io/playground-testing/playground-runs.json",
    #     "format": "playwright",
    # },
]


def parse_iso_to_ist(ts: str) -> datetime | None:
    """Parse ISO timestamp into IST datetime."""
    if not ts:
        return None
    try:
        # Handle "2026-04-16T09:55:12.734Z" and "2026-04-16 09:55:12 IST"
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
    """Normalize different project formats into {timestamp, total, passed, failed, pass_rate}."""
    out = []
    if fmt == "playwright":
        # Two sub-formats observed:
        #   (A) {id|runId, startedAt, summary:{total,passed,failed,skipped,timedOut}, passRate}  (Console/Widget/Asksam)
        #   (B) {runId, runDate, total, passed, failed, passRate}              (Website)
        for r in raw:
            summary = r.get("summary") or {}
            ts = r.get("startedAt") or r.get("runDate")
            total = summary.get("total", r.get("total", 0))
            passed = summary.get("passed", r.get("passed", 0))
            skipped = summary.get("skipped", r.get("skipped", 0))
            explicit_failed = summary.get("failed", r.get("failed", 0))
            timed_out = summary.get("timedOut", r.get("timedOut", 0))
            # Treat any test that didn't pass and wasn't intentionally skipped as failed
            # (covers timedOut, flaky, etc.) so our counts match each project's own dashboard.
            failed = max(total - passed - skipped, 0) if total else explicit_failed + timed_out
            out.append({
                "timestamp": ts,
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": r.get("passRate", 0),
            })
    elif fmt == "vak":
        # raw is {runs: [{timestamp, total, passed, failed, pass_rate}], current: {...}}
        for r in raw.get("runs", []):
            out.append({
                "timestamp": r.get("timestamp"),
                "total": r.get("total", 0),
                "passed": r.get("passed", 0),
                "failed": r.get("failed", 0),
                "pass_rate": r.get("pass_rate", 0),
            })
    return out


def filter_yesterday(runs: list[dict], yesterday: datetime) -> list[dict]:
    """Keep only runs that happened on the given IST date."""
    target = yesterday.date()
    out = []
    for r in runs:
        dt = parse_iso_to_ist(r.get("timestamp", ""))
        if dt and dt.date() == target:
            out.append({**r, "_dt": dt})
    return out


def fetch_project(project: dict) -> dict:
    """Fetch & normalize a project's runs. Returns {ok, runs[], error}."""
    try:
        r = httpx.get(project["runs_url"], timeout=15, follow_redirects=True)
        r.raise_for_status()
        runs = normalize_runs(r.json(), project["format"])
        return {"ok": True, "runs": runs, "error": ""}
    except Exception as e:
        return {"ok": False, "runs": [], "error": str(e)[:200]}


def build_project_section(project: dict, ydays_runs: list[dict], fetch_error: str) -> dict:
    """Build summary stats + html row for one project."""
    if fetch_error:
        return {
            "name": project["name"],
            "status": "ERROR",
            "total_runs": 0,
            "failed_runs": 0,
            "failed_times": [],
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0,
            "dashboard": project["dashboard"],
            "error": fetch_error,
        }
    if not ydays_runs:
        return {
            "name": project["name"],
            "status": "NO_DATA",
            "total_runs": 0,
            "failed_runs": 0,
            "failed_times": [],
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0,
            "dashboard": project["dashboard"],
            "error": "",
        }
    total_runs = len(ydays_runs)
    failed_runs = [r for r in ydays_runs if r["failed"] > 0]
    failed_times = [r["_dt"].strftime("%I:%M %p") for r in failed_runs]
    total = sum(r["total"] for r in ydays_runs)
    passed = sum(r["passed"] for r in ydays_runs)
    failed = sum(r["failed"] for r in ydays_runs)
    pass_rate = round(passed / total * 100, 1) if total else 0
    return {
        "name": project["name"],
        "status": "OK",
        "total_runs": total_runs,
        "failed_runs": len(failed_runs),
        "failed_times": failed_times,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "dashboard": project["dashboard"],
        "error": "",
    }


def render_html(sections: list[dict], yesterday: datetime) -> tuple[str, str]:
    date_str = yesterday.strftime("%a, %b %d, %Y")
    overall_total = sum(s["total"] for s in sections)
    overall_passed = sum(s["passed"] for s in sections)
    overall_failed = sum(s["failed"] for s in sections)
    overall_rate = round(overall_passed / overall_total * 100, 1) if overall_total else 0
    projects_with_failures = sum(1 for s in sections if s["failed"] > 0)
    total_runs_all = sum(s["total_runs"] for s in sections)
    failed_runs_all = sum(s["failed_runs"] for s in sections)

    rows = ""
    for s in sections:
        if s["status"] == "ERROR":
            badge = '<span style="background:#fef2f2;color:#991b1b;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">ERROR</span>'
            stats_cell = f'<td colspan="6" style="padding:12px 16px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#991b1b;">{s["error"]}</td>'
        elif s["status"] == "NO_DATA":
            badge = '<span style="background:#f3f4f6;color:#6b7280;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">NO RUNS</span>'
            stats_cell = '<td colspan="6" style="padding:12px 16px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#888;">No runs on this date</td>'
        else:
            if s["failed"] == 0:
                badge = f'<span style="background:#dcfce7;color:#166534;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">{s["pass_rate"]}% PASS</span>'
            elif s["pass_rate"] >= 90:
                badge = f'<span style="background:#fef3c7;color:#92400e;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">{s["pass_rate"]}% PASS</span>'
            else:
                badge = f'<span style="background:#fef2f2;color:#991b1b;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">{s["pass_rate"]}% PASS</span>'

            failed_runs_cell = (
                f'<span style="color:#ef4444;font-weight:700;">{s["failed_runs"]}</span>'
                if s["failed_runs"] > 0
                else '<span style="color:#22c55e;font-weight:600;">0</span>'
            )
            failed_times_html = ", ".join(s["failed_times"]) if s["failed_times"] else "—"

            stats_cell = (
                f'<td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-size:13px;font-weight:600;">{s["total_runs"]}</td>'
                f'<td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-size:13px;">{failed_runs_cell}</td>'
                f'<td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-size:11px;color:#991b1b;max-width:160px;">{failed_times_html}</td>'
                f'<td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-size:13px;font-weight:600;">{s["total"]}</td>'
                f'<td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;color:#22c55e;font-weight:600;font-size:13px;">{s["passed"]}</td>'
                f'<td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;color:#ef4444;font-weight:600;font-size:13px;">{s["failed"]}</td>'
            )

        rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;font-size:13px;">
            <div style="font-weight:600;color:#333;">{s["name"]}</div>
            <a href="{s["dashboard"]}" style="font-size:11px;color:#7c3aed;text-decoration:none;">View Dashboard →</a>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;text-align:center;">{badge}</td>
          {stats_cell}
        </tr>"""

    # If a row used colspan, the per-project columns are missing. Use a unified table instead.
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:720px;margin:24px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:linear-gradient(135deg,#7c3aed,#a855f7);padding:28px 32px;color:#fff;">
      <h1 style="margin:0;font-size:24px;font-weight:700;">Daily QA Health Report</h1>
      <p style="margin:6px 0 0;font-size:14px;opacity:0.9;">All automation projects — yesterday's results</p>
      <p style="margin:8px 0 0;font-size:13px;opacity:0.8;">Date: {date_str}</p>
    </div>

    <div style="padding:20px 32px;">
      <table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:separate;border-spacing:8px 8px;">
        <tr>
          <td width="25%" style="border:2px solid #e5e7eb;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Projects</div>
            <div style="font-size:22px;font-weight:700;color:#333;margin-top:4px;">{len(sections)}</div>
          </td>
          <td width="25%" style="border:2px solid #e5e7eb;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Total Runs</div>
            <div style="font-size:22px;font-weight:700;color:#333;margin-top:4px;">{total_runs_all}</div>
          </td>
          <td width="25%" style="border:2px solid #fecaca;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Failed Runs</div>
            <div style="font-size:22px;font-weight:700;color:#ef4444;margin-top:4px;">{failed_runs_all}</div>
          </td>
          <td width="25%" style="border:2px solid #e5e7eb;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Total Tests</div>
            <div style="font-size:22px;font-weight:700;color:#333;margin-top:4px;">{overall_total}</div>
          </td>
        </tr>
        <tr>
          <td width="33%" style="border:2px solid #dcfce7;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Passed</div>
            <div style="font-size:22px;font-weight:700;color:#22c55e;margin-top:4px;">{overall_passed}</div>
          </td>
          <td width="33%" style="border:2px solid #fecaca;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Failed</div>
            <div style="font-size:22px;font-weight:700;color:#ef4444;margin-top:4px;">{overall_failed}</div>
          </td>
          <td width="34%" style="border:2px solid #e5e7eb;border-radius:12px;padding:12px 6px;text-align:center;">
            <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">Pass Rate</div>
            <div style="font-size:22px;font-weight:700;color:{('#22c55e' if overall_rate>=95 else '#f59e0b' if overall_rate>=80 else '#ef4444')};margin-top:4px;">{overall_rate}%</div>
          </td>
        </tr>
      </table>
    </div>

    <div style="margin:0 32px 24px;">
      <h3 style="font-size:16px;margin:0 0 12px 0;color:#333;">Project Breakdown</h3>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:10px 16px;text-align:left;font-size:12px;font-weight:600;color:#666;">Project</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Status</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Total Runs</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#ef4444;">Failed Runs</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Failure Times (IST)</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#666;">Total Tests</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#22c55e;">Pass</th>
            <th style="padding:10px 16px;text-align:center;font-size:12px;font-weight:600;color:#ef4444;">Fail</th>
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

    if overall_failed > 0:
        subject = f"Daily QA Health Report – {date_str} – {projects_with_failures}/{len(sections)} projects with failures"
    elif overall_total == 0:
        subject = f"Daily QA Health Report – {date_str} – No runs found"
    else:
        subject = f"Daily QA Health Report – {date_str} – All Green ({overall_rate}%)"
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
    yesterday = datetime.now(IST) - timedelta(days=1)

    sections = []
    for proj in PROJECTS:
        fetched = fetch_project(proj)
        ydays = filter_yesterday(fetched["runs"], yesterday) if fetched["ok"] else []
        sections.append(build_project_section(proj, ydays, fetched["error"]))

    html, subject = render_html(sections, yesterday)
    print(f"Subject: {subject}")
    for s in sections:
        print(f"  {s['name']}: status={s['status']} total_runs={s['total_runs']} failed_runs={s['failed_runs']} total={s['total']} pass={s['passed']} fail={s['failed']}")

    if preview:
        out = Path(__file__).parent / "digest_preview.html"
        out.write_text(html)
        print(f"Preview saved: {out}")
    else:
        send_email(html, subject)


if __name__ == "__main__":
    main()
