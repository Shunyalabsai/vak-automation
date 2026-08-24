#!/usr/bin/env python3
"""
Generate HTML email report and send via Google Apps Script Web App.

Usage:
    python email_report.py                    # Send email using latest_report.json
    python email_report.py --preview          # Save HTML to email_preview.html (no send)

Environment variables:
    EMAIL_WEB_APP_URL  — Google Apps Script Web App URL for sending email
    EMAIL_RECIPIENTS   — Comma-separated email addresses
    DASHBOARD_URL      — URL to the GitHub Pages dashboard
    GOOGLE_SHEET_URL   — Link to the Google Sheet (optional; hides button if unset)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

IST = timezone(timedelta(hours=5, minutes=30))
DOCS_DIR = Path(__file__).parent / "docs"
DATA_FILE = DOCS_DIR / "data.json"
REPORT_FILE = Path(__file__).parent / "test_output" / "latest_report.json"


def load_data():
    """Load dashboard data.json for run history + current results."""
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return None


def load_latest_results():
    """Load latest_report.json for current test details."""
    if REPORT_FILE.exists():
        return json.loads(REPORT_FILE.read_text())
    return []


def generate_email_html(data: dict, results: list[dict]) -> tuple[str, str]:
    """Generate HTML email body and subject line."""
    current = data.get("current", {})
    runs = data.get("runs", [])

    total = current.get("total", 0)
    passed = current.get("passed", 0)
    failed = current.get("failed", 0)
    pass_rate = current.get("pass_rate", 0)
    ts = current.get("timestamp", datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"))
    categories = current.get("categories", [])

    # Count today's runs
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    todays_runs = sum(1 for r in runs if r.get("timestamp", "").startswith(today_str))

    # Format timestamp for display
    try:
        dt = datetime.strptime(ts.replace(" IST", ""), "%Y-%m-%d %H:%M:%S")
        display_date = dt.strftime("%a, %b %d, %Y, %I:%M %p")
    except ValueError:
        display_date = ts

    # Pass rate emoji/color
    if pass_rate == 100:
        rate_emoji = "🟢"
        rate_color = "#22c55e"
    elif pass_rate >= 90:
        rate_emoji = "🟡"
        rate_color = "#f59e0b"
    else:
        rate_emoji = "🔴"
        rate_color = "#ef4444"

    # Failed tests
    failed_tests = [r for r in results if r.get("status") == "FAIL"]

    # Category rows
    category_rows = ""
    for cat in categories:
        cat_name = cat["name"]
        cat_pass = cat["pass"]
        cat_fail = cat["fail"]
        cat_rate = cat.get("pass_rate", 0)
        if cat_fail == 0:
            icon = "✅"
            dot_color = "#22c55e"
        else:
            icon = "🔴"
            dot_color = "#ef4444"
        category_rows += f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;font-size:14px;">
            <span style="color:{dot_color};margin-right:6px;">{icon}</span> {cat_name}
          </td>
          <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;text-align:center;color:#22c55e;font-weight:600;">{cat_pass}</td>
          <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;text-align:center;color:#ef4444;font-weight:600;">{cat_fail}</td>
          <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;text-align:center;font-weight:600;">{cat_rate}%</td>
        </tr>"""

    # Failed tests rows
    failed_rows = ""
    if failed_tests:
        for ft in failed_tests:
            if ft.get("test_type") == "Pipeline":
                name = f"Pipeline {ft.get('source_lang', '')}→{ft.get('target_lang', '')} ({ft.get('input', '')})"
                module = "Pipeline"
            else:
                name = ft.get("test_name", ft.get("endpoint", ""))
                module = ft.get("endpoint", "Unknown")
            error = ft.get("error", "")[:150]
            response = (ft.get("response") or ft.get("output") or ft.get("notes") or "")[:150]
            failed_rows += f"""
            <tr>
              <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;font-size:13px;">{name}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;text-align:center;color:#f59e0b;font-weight:600;font-size:13px;">{module}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#666;word-break:break-all;">{error}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#444;word-break:break-all;">{response or "-"}</td>
            </tr>"""

    failed_section = ""
    if failed_tests:
        failed_section = f"""
        <div style="margin:24px 32px;">
          <h3 style="font-size:16px;margin:0 0 12px 0;color:#333;">
            <span style="color:#ef4444;">🔴</span> Failed Tests
          </h3>
          <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
            <thead>
              <tr style="background:#fef2f2;">
                <th style="padding:10px 16px;text-align:left;font-size:13px;font-weight:600;color:#666;">Test Name</th>
                <th style="padding:10px 16px;text-align:center;font-size:13px;font-weight:600;color:#666;">Module</th>
                <th style="padding:10px 16px;text-align:left;font-size:13px;font-weight:600;color:#666;">Error</th>
                <th style="padding:10px 16px;text-align:left;font-size:13px;font-weight:600;color:#666;">Received Response</th>
              </tr>
            </thead>
            <tbody>{failed_rows}</tbody>
          </table>
        </div>"""

    dashboard_url = os.environ.get("DASHBOARD_URL", "https://shunyalabsai.github.io/vak-automation/")
    sheet_url = os.environ.get("GOOGLE_SHEET_URL", "")
    sheet_button = ""
    if sheet_url:
        sheet_button = f"""
      <a href="{sheet_url}" style="display:inline-block;background:#f59e0b;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;font-size:14px;margin:6px;">
        📋 View Test Cases
      </a>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:640px;margin:24px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#7c3aed,#a855f7);padding:28px 32px;color:#fff;">
      <div style="font-size:12px;margin-bottom:8px;">⭐</div>
      <h1 style="margin:0;font-size:24px;font-weight:700;">Vak API Automation Report</h1>
      <p style="margin:4px 0 0;font-size:14px;opacity:0.9;">Vak API — ASR, Translate, TTS</p>
      <p style="margin:8px 0 0;font-size:13px;opacity:0.8;">Latest Run: {display_date}</p>
      <span style="display:inline-block;margin-top:10px;background:rgba(255,255,255,0.2);padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600;">Today's Runs: {todays_runs}</span>
    </div>

    <!-- Stats Cards -->
    <div style="display:flex;justify-content:center;gap:16px;padding:24px 32px;flex-wrap:wrap;">
      <div style="flex:1;min-width:100px;border:2px solid #e5e7eb;border-radius:12px;padding:16px;text-align:center;">
        <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Total Tests</div>
        <div style="font-size:28px;font-weight:700;color:#333;margin-top:4px;">{total}</div>
      </div>
      <div style="flex:1;min-width:100px;border:2px solid #dcfce7;border-radius:12px;padding:16px;text-align:center;">
        <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Passed</div>
        <div style="font-size:28px;font-weight:700;color:#22c55e;margin-top:4px;">{passed}</div>
      </div>
      <div style="flex:1;min-width:100px;border:2px solid #fecaca;border-radius:12px;padding:16px;text-align:center;">
        <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Failed</div>
        <div style="font-size:28px;font-weight:700;color:#ef4444;margin-top:4px;">{failed}</div>
      </div>
      <div style="flex:1;min-width:100px;border:2px solid #e5e7eb;border-radius:12px;padding:16px;text-align:center;">
        <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Pass Rate</div>
        <div style="font-size:16px;margin-top:6px;">{rate_emoji}</div>
        <div style="font-size:20px;font-weight:700;color:{rate_color};">{pass_rate}%</div>
      </div>
    </div>

    <!-- Results by Module -->
    <div style="margin:0 32px 24px;">
      <h3 style="font-size:16px;margin:0 0 12px 0;color:#333;">
        <span style="margin-right:6px;">📊</span> Results by Module
      </h3>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:10px 16px;text-align:left;font-size:13px;font-weight:600;color:#666;">Module</th>
            <th style="padding:10px 16px;text-align:center;font-size:13px;font-weight:600;color:#22c55e;">Pass</th>
            <th style="padding:10px 16px;text-align:center;font-size:13px;font-weight:600;color:#ef4444;">Fail</th>
            <th style="padding:10px 16px;text-align:center;font-size:13px;font-weight:600;color:#666;">Rate</th>
          </tr>
        </thead>
        <tbody>{category_rows}</tbody>
      </table>
    </div>

    {failed_section}

    <!-- Buttons -->
    <div style="text-align:center;padding:16px 32px 28px;">
      <a href="{dashboard_url}" style="display:inline-block;background:#7c3aed;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;font-size:14px;margin:6px;">
        📊 View Full Dashboard
      </a>{sheet_button}
    </div>

    <!-- Footer -->
    <div style="border-top:1px solid #e5e7eb;padding:20px 32px;text-align:center;">
      <p style="margin:0;font-size:13px;color:#888;">Thanks & Regards,</p>
      <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#333;">Saira Automation BOT 🤖</p>
      <p style="margin:8px 0 0;font-size:11px;color:#aaa;">This is an automated report generated from the latest test run.</p>
    </div>

    <div style="background:#f9fafb;padding:8px;text-align:center;">
      <p style="margin:0;font-size:10px;color:#ccc;letter-spacing:1px;">CONFIDENTIAL COMMUNICATION</p>
    </div>
  </div>
</body>
</html>"""

    # Subject line
    day_str = datetime.now(IST).strftime("%A, %b %d, %Y")
    subject = f"Vak API Automation Report – {day_str} – {pass_rate}% Pass Rate"

    return html, subject


def send_email(html: str, subject: str):
    """Send email via Google Apps Script Web App."""
    web_app_url = os.environ.get("EMAIL_WEB_APP_URL", "")
    recipients = os.environ.get("EMAIL_RECIPIENTS", "")

    if not web_app_url:
        print("EMAIL_WEB_APP_URL not set. Skipping email send.")
        return False
    if not recipients:
        print("EMAIL_RECIPIENTS not set. Skipping email send.")
        return False

    payload = {
        "to": recipients,
        "subject": subject,
        "body": html,
    }

    resp = httpx.post(web_app_url, json=payload, timeout=60, follow_redirects=True)
    if resp.status_code == 200:
        try:
            body = resp.json()
            if body.get("ok"):
                print(f"Email sent to: {recipients}")
                return True
            else:
                print(f"Email send failed: {body.get('error', 'unknown')}")
                return False
        except Exception:
            # Apps Script may return HTML on success (redirect page)
            text = resp.text[:200]
            if "error" in text.lower():
                print(f"Email may have failed. Response: {text}")
                return False
            print(f"Email likely sent (non-JSON response). Recipients: {recipients}")
            return True
    else:
        print(f"Email HTTP error: {resp.status_code} - {resp.text[:200]}")
        return False


def main():
    preview = "--preview" in sys.argv

    data = load_data()
    if not data or not data.get("current"):
        print("No dashboard data found. Run report_to_sheet.py first.")
        sys.exit(1)

    current = data.get("current", {})
    failed = current.get("failed", 0)

    # Only send email if there are failures in the last run
    if not preview and failed == 0:
        print(f"Last run: {current.get('passed', 0)} passed, 0 failed. All good — skipping email.")
        return

    results = load_latest_results()
    # If no local report, reconstruct from dashboard data
    if not results and current.get("tests"):
        results = current["tests"]
    html, subject = generate_email_html(data, results)

    if preview:
        preview_path = Path(__file__).parent / "email_preview.html"
        preview_path.write_text(html)
        print(f"Email preview saved: {preview_path}")
        print(f"Subject: {subject}")
    else:
        print(f"Last run had {failed} failure(s) — sending report email.")
        send_email(html, subject)


if __name__ == "__main__":
    main()
