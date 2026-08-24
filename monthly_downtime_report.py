#!/usr/bin/env python3
"""
Monthly downtime email — uses the same rules and totals as docs/failures.html.

Usage:
    python monthly_downtime_report.py --preview --month 2026-05
    python monthly_downtime_report.py --test-send --to you@company.com --month 2026-05
"""
from __future__ import annotations

import os
import re
import sys
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

IST = timezone(timedelta(hours=5, minutes=30))

PROJECTS = [
    {
        "name": "Asksam Automation",
        "dashboard": "https://saira-uwc.github.io/asksam-automation-new/",
        "runs_url": "https://saira-uwc.github.io/asksam-automation-new/history/runs.json",
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
    {
        "name": "Concurrent (Zero Indic)",
        "dashboard": "https://yamini-pal-singh.github.io/automation-testing/Concurrent-Report.html",
        "runs_url": "https://yamini-pal-singh.github.io/automation-testing/concurrent-runs.json",
        "format": "playwright",
    },
    {
        "name": "Long Audio (Zero Indic)",
        "dashboard": "https://yamini-pal-singh.github.io/automation-testing/Long-Audio-Report.html",
        "runs_url": "https://yamini-pal-singh.github.io/automation-testing/long-audio-runs.json",
        "format": "playwright",
    },
    {
        "name": "Playground",
        "dashboard": "https://yamini-pal-singh.github.io/playground-testing/Playground-Report.html",
        "runs_url": "https://yamini-pal-singh.github.io/playground-testing/playground-runs.json",
        "format": "playwright",
    },
]

FAILURES_DASHBOARD = "https://shunyalabsai.github.io/vak-automation/failures.html"


def is_downtime_failure(msg: str, status_code: int | None = None) -> bool:
    """Must stay in sync with isDowntimeFailure() in docs/failures.html."""
    s = (msg or "").lower()
    if status_code is not None and status_code >= 500:
        return True
    if re.search(r"\b5\d{2}\b", s):
        return True
    for needle in (
        "bad gateway",
        "gateway timeout",
        "service unavailable",
        "internal server error",
        "too many requests",
        "429",
        "connection refused",
        "connection reset",
        "dns",
        "enotfound",
        "eai_again",
        "tls",
        "ssl",
        "transporterror",
        "transport error",
        "httpx.",
        "http error",
    ):
        if needle in s:
            return True
    return False


def parse_iso_to_ist(ts: str) -> datetime | None:
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


def date_key_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%Y-%m-%d")


def month_key_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%Y-%m")


VAK_COMPONENT_LABELS = {
    "ASR": "ASR (speech-to-text)",
    "Translate": "Translate",
    "TTS": "TTS (text-to-speech)",
    "Pipeline": "Pipeline (ASR &gt; Translate &gt; TTS)",
}
VAK_COMPONENT_ORDER = ["ASR", "Translate", "TTS", "Pipeline"]


def component_from_vak_failure(f: dict) -> str:
    cat = (f.get("category") or "").strip()
    if cat in VAK_COMPONENT_LABELS:
        return cat
    name = (f.get("name") or "").lower()
    if name.startswith("asr") or "asr" in name:
        return "ASR"
    if "translate" in name:
        return "Translate"
    if name.startswith("tts") or "tts" in name:
        return "TTS"
    if (f.get("test_type") or "") == "Pipeline":
        return "Pipeline"
    return "Other API"


def component_from_playwright_item(item: dict) -> str:
    mod = (item.get("module") or "").strip()
    if mod:
        return mod
    title = (item.get("title") or "").lower()
    if "asr" in title or "transcri" in title or "speech-to-text" in title:
        return "ASR"
    if "translate" in title or "translation" in title:
        return "Translate"
    if "tts" in title or "text-to-speech" in title or "speech" in title:
        return "TTS"
    if "pipeline" in title:
        return "Pipeline"
    return "Automation tests"


def _downtime_items_from_playwright_run(r: dict) -> list[dict]:
    items = []
    if isinstance(r.get("tests"), list):
        for t in r["tests"]:
            status = (t.get("status") or "").lower()
            if status in ("passed", "pass", "skipped", "skip", ""):
                continue
            err = t.get("error") or t.get("comment") or ""
            if is_downtime_failure(err):
                raw = {
                    "title": t.get("title") or t.get("name") or "(unnamed)",
                    "module": t.get("moduleLabel") or t.get("module") or t.get("moduleName") or "",
                }
                items.append({**raw, "component": component_from_playwright_item(raw)})
    if not items and isinstance(r.get("suites"), list):
        for s in r["suites"]:
            status = (s.get("status") or "").lower()
            if status not in ("fail", "failed"):
                continue
            err = s.get("failure_reason") or ""
            if is_downtime_failure(err):
                raw = {
                    "title": s.get("name") or "(unnamed suite)",
                    "module": s.get("category") or "",
                }
                items.append({**raw, "component": component_from_playwright_item(raw)})
    return items


def normalize_runs(raw, fmt: str) -> list[dict]:
    """Same shape as failures.html normalize(): failed = downtime incident count."""
    out = []
    if fmt == "vak":
        for r in raw.get("runs", []):
            downtime = [
                f for f in (r.get("failed_tests") or [])
                if is_downtime_failure(f.get("error", ""))
            ]
            items = [
                {**f, "component": component_from_vak_failure(f)}
                for f in downtime
            ]
            out.append({
                "timestamp": r.get("timestamp"),
                "failed": len(items),
                "items": items,
            })
        return out

    runs_raw = raw if isinstance(raw, list) else []
    for r in runs_raw:
        items = _downtime_items_from_playwright_run(r)
        ts = r.get("startedAt") or r.get("runTimestamp") or r.get("runDate")
        out.append({"timestamp": ts, "failed": len(items), "items": items})
    return out


def resolve_report_month() -> tuple[int, int]:
    for arg in sys.argv[1:]:
        if arg.startswith("--month"):
            parts = arg.split("=", 1)
            if len(parts) == 2:
                y, m = parts[1].split("-")
                return int(y), int(m)
            idx = sys.argv.index(arg)
            if idx + 1 < len(sys.argv):
                y, m = sys.argv[idx + 1].split("-")
                return int(y), int(m)
    now = datetime.now(IST)
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_prev = first_this - timedelta(days=1)
    return last_prev.year, last_prev.month


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    last_day = monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=IST)
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=IST)
    return start, end


def fetch_project(project: dict) -> dict:
    try:
        r = httpx.get(project["runs_url"], timeout=20, follow_redirects=True)
        r.raise_for_status()
        runs = normalize_runs(r.json(), project["format"])
        return {"ok": True, "runs": runs, "error": ""}
    except Exception as e:
        return {"ok": False, "runs": [], "error": str(e)[:200]}


def build_day_index(project_entries: list[dict], year: int, month: int) -> dict:
    """Mirrors buildDayIndex() in failures.html for one calendar month."""
    target = f"{year:04d}-{month:02d}"
    days: dict[str, dict] = {}

    for entry in project_entries:
        if entry.get("error"):
            continue
        name = entry["project"]["name"]
        start, end = month_bounds(year, month)
        for r in entry["runs"]:
            dt = parse_iso_to_ist(r.get("timestamp", ""))
            if not dt or not (start <= dt <= end):
                continue
            k = date_key_ist(dt)
            if k not in days:
                days[k] = {"failed_runs": 0, "failed_tests": 0, "projects": set()}
            day = days[k]
            if r["failed"] > 0:
                day["failed_runs"] += 1
                day["failed_tests"] += r["failed"]
                day["projects"].add(name)
    return days


def build_month_summary(day_index: dict) -> dict:
    """Mirrors buildMonthSummary() in failures.html."""
    incidents = downtime_runs = 0
    projs: set[str] = set()
    for day in day_index.values():
        incidents += day["failed_tests"]
        downtime_runs += day["failed_runs"]
        projs |= day["projects"]
    downtime_days = sum(1 for d in day_index.values() if d["failed_runs"] > 0)
    return {
        "incidents": incidents,
        "downtime_runs": downtime_runs,
        "downtime_days": downtime_days,
        "projects_affected": len(projs),
    }


def build_project_row(project: dict, runs: list[dict], year: int, month: int) -> dict:
    start, end = month_bounds(year, month)
    month_runs = []
    for r in runs:
        dt = parse_iso_to_ist(r.get("timestamp", ""))
        if dt and start <= dt <= end:
            month_runs.append({**r, "_dt": dt})

    downtime_runs = [r for r in month_runs if r["failed"] > 0]
    days = {date_key_ist(r["_dt"]) for r in downtime_runs}
    components_hit: set[str] = set()
    for r in downtime_runs:
        for item in r.get("items") or []:
            comp = item.get("component") or "Other"
            components_hit.add(comp)

    return {
        "name": project["name"],
        "dashboard": project["dashboard"],
        "format": project.get("format", ""),
        "total_runs": len(month_runs),
        "downtime_runs": len(downtime_runs),
        "downtime_days": len(days),
        "components_hit": components_hit,
        "healthy": len(month_runs) > 0 and len(downtime_runs) == 0,
        "no_data": len(month_runs) == 0,
    }


def format_components_list(project_row: dict) -> str:
    """Names only — which parts of the flow had downtime (no per-test counts)."""
    hit = project_row.get("components_hit") or set()
    if not hit:
        return ""

    if project_row.get("format") == "vak" or project_row["name"] == "Vak BE Automation":
        parts = [VAK_COMPONENT_LABELS[k].split(" (")[0] for k in VAK_COMPONENT_ORDER if k in hit]
        for k in sorted(hit):
            if k not in VAK_COMPONENT_ORDER:
                parts.append(k)
        return ", ".join(parts)

    return ", ".join(sorted(hit))


def render_html(
    month_label: str,
    summary: dict,
    project_rows: list[dict],
) -> tuple[str, str]:
    n_projects = len(PROJECTS)
    runs = summary["downtime_runs"]
    days = summary["downtime_days"]
    projs = summary["projects_affected"]
    times_word = "time" if runs == 1 else "times"

    if runs == 0:
        highlight = (
            f'<div style="background:#dcfce7;border:1px solid #86efac;border-radius:8px;'
            f'padding:14px 24px;margin:0 24px 16px;color:#166534;font-size:13px;">'
            f'<strong>{month_label}:</strong> No API downtime this month.</div>'
        )
    else:
        highlight = (
            f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;'
            f'padding:14px 24px;margin:0 24px 16px;color:#991b1b;font-size:13px;line-height:1.55;">'
            f'<strong>{month_label}</strong><br>'
            f'Systems went down <strong>{runs}</strong> {times_word} '
            f'({runs} scheduled run{"s" if runs != 1 else ""} hit API errors) '
            f'across <strong>{days}</strong> day{"s" if days != 1 else ""}. '
            f'<strong>{projs}</strong> project{"s" if projs != 1 else ""} affected.</div>'
        )

    stat = lambda label, val, sub, danger: f"""
      <td width="25%" style="border:1px solid #e5e7eb;border-radius:10px;padding:12px 8px;text-align:center;">
        <div style="font-size:10px;font-weight:600;color:#888;text-transform:uppercase;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:{'#ef4444' if danger else '#22c55e'};margin-top:4px;">{val}</div>
        <div style="font-size:10px;color:#aaa;margin-top:2px;">{sub}</div>
      </td>"""

    stats_row = (
        stat("Times down", runs, "scheduled runs with API errors", runs > 0)
        + stat("Downtime days", days, "days with at least one outage", days > 0)
        + stat("Projects down", f"{projs}/{n_projects}", "had downtime this month", projs > 0)
    )

    affected_lines = ""
    for p in project_rows:
        if p["downtime_runs"] == 0:
            continue
        services = format_components_list(p)
        tw = "time" if p["downtime_runs"] == 1 else "times"
        services_line = (
            f'<br><span style="font-size:12px;color:#666;">Services hit: {services}</span>'
            if services else ""
        )
        affected_lines += (
            f'<li style="margin:8px 0;font-size:13px;color:#333;">'
            f'<strong>{p["name"]}</strong> - down '
            f'<span style="color:#ef4444;font-weight:600;">{p["downtime_runs"]}</span> {tw} '
            f'over {p["downtime_days"]} day{"s" if p["downtime_days"] != 1 else ""}'
            f'{services_line}</li>'
        )

    vak_row = next((p for p in project_rows if p["name"] == "Vak BE Automation"), None)
    vak_flow_block = ""
    if vak_row and vak_row.get("components_hit"):
        tags = ""
        for key in VAK_COMPONENT_ORDER:
            if key in vak_row["components_hit"]:
                label = VAK_COMPONENT_LABELS[key].split(" (")[0]
                tags += (
                    f'<span style="display:inline-block;background:#ede9fe;color:#5b21b6;'
                    f'padding:5px 12px;border-radius:16px;font-size:12px;font-weight:600;margin:3px;">'
                    f'{label}</span>'
                )
        if tags:
            vak_flow_block = (
                f'<div style="margin:0 24px 16px;padding:12px 14px;background:#faf5ff;'
                f'border:1px solid #e9d5ff;border-radius:8px;">'
                f'<div style="font-size:11px;font-weight:700;color:#7c3aed;text-transform:uppercase;'
                f'margin-bottom:8px;">Vak - which services had downtime</div>'
                f'{tags}</div>'
            )

    healthy = [p["name"] for p in project_rows if p.get("healthy")]
    healthy_block = ""
    if healthy:
        pills = "".join(
            f'<span style="display:inline-block;background:#dcfce7;color:#166534;'
            f'padding:4px 10px;border-radius:16px;font-size:11px;font-weight:600;margin:3px;">{n}</span>'
            for n in healthy
        )
        healthy_block = (
            f'<div style="margin:0 24px 16px;padding:12px 14px;background:#f9fafb;border-radius:8px;">'
            f'<div style="font-size:11px;font-weight:700;color:#22c55e;text-transform:uppercase;margin-bottom:8px;">'
            f'All passing · {len(healthy)}</div>{pills}</div>'
        )

    affected_block = ""
    if affected_lines:
        affected_block = (
            f'<div style="margin:0 24px 16px;">'
            f'<div style="font-size:12px;font-weight:700;color:#666;text-transform:uppercase;margin-bottom:8px;">'
            f'Projects with downtime</div>'
            f'<ul style="margin:0;padding-left:18px;">{affected_lines}</ul></div>'
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:560px;margin:20px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
    <div style="background:linear-gradient(135deg,#7c3aed,#6d28d9);padding:20px 24px;color:#fff;">
      <h1 style="margin:0;font-size:20px;font-weight:700;">QA Downtime Tracker</h1>
      <p style="margin:6px 0 0;font-size:13px;opacity:0.9;">Monthly summary · API / system outages only</p>
      <p style="margin:8px 0 0;font-size:15px;font-weight:600;">{month_label}</p>
    </div>

    {highlight}

    {vak_flow_block}

    <div style="padding:8px 24px 12px;">
      <table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="border-collapse:separate;border-spacing:6px;">
        <tr>{stats_row}</tr>
      </table>
    </div>

    {affected_block}
    {healthy_block}

    <div style="padding:10px 24px 18px;font-size:12px;color:#888;text-align:center;">
      Same data as <a href="{FAILURES_DASHBOARD}" style="color:#7c3aed;">QA Downtime Tracker</a>
    </div>
    <div style="border-top:1px solid #eee;padding:12px 24px;text-align:center;font-size:12px;color:#888;">
      Saira Automation BOT
    </div>
  </div>
</body></html>"""

    if runs == 0:
        subject = f"{month_label} Monthly Downtime Summary — no outages this month"
    else:
        proj_word = "project" if projs == 1 else "projects"
        subject = (
            f"{month_label} Monthly Downtime Summary — "
            f"down {runs} {times_word} over {days} day{'s' if days != 1 else ''}, "
            f"{projs} {proj_word} affected"
        )
    return html, subject


def send_email(html: str, subject: str, recipients: str | None = None) -> bool:
    url = os.environ.get("EMAIL_WEB_APP_URL", "")
    to = recipients or os.environ.get("EMAIL_RECIPIENTS", "")
    if not url or not to:
        print("EMAIL_WEB_APP_URL or recipient not set.")
        return False
    payload = {"to": to, "subject": subject, "body": html}
    resp = httpx.post(url, json=payload, timeout=60, follow_redirects=True)
    if resp.status_code == 200:
        try:
            body = resp.json()
            if body.get("ok"):
                print(f"Monthly report sent to: {to}")
                return True
            print(f"Send failed: {body.get('error')}")
            return False
        except Exception:
            print(f"Monthly report likely sent. To: {to}")
            return True
    print(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return False


def _arg_value(flag: str) -> str | None:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main():
    preview = "--preview" in sys.argv
    test_send = "--test-send" in sys.argv
    test_to = _arg_value("--to")
    year, month = resolve_report_month()
    month_label = datetime(year, month, 1, tzinfo=IST).strftime("%B %Y")
    print(f"Building QA downtime monthly summary for {month_label} (same rules as failures.html)...")

    project_entries = []
    project_rows = []
    for proj in PROJECTS:
        fetched = fetch_project(proj)
        project_entries.append({
            "project": proj,
            "runs": fetched["runs"] if fetched["ok"] else [],
            "error": fetched["error"],
        })
        if fetched["ok"]:
            project_rows.append(build_project_row(proj, fetched["runs"], year, month))

    day_index = build_day_index(project_entries, year, month)
    summary = build_month_summary(day_index)
    html, subject = render_html(month_label, summary, project_rows)

    print(f"Subject: {subject}")
    print(
        f"  Totals: down {summary['downtime_runs']} time(s), "
        f"{summary['downtime_days']} day(s), {summary['projects_affected']} project(s)"
    )
    for p in project_rows:
        if p["downtime_runs"]:
            svc = format_components_list(p)
            print(
                f"  {p['name']}: down {p['downtime_runs']} time(s), "
                f"{p['downtime_days']} day(s)"
                + (f", services: {svc}" if svc else "")
            )

    if preview or test_send:
        out = Path(__file__).parent / "monthly_downtime_preview.html"
        out.write_text(html, encoding="utf-8")
        print(f"Preview saved: {out}")

    if test_send:
        send_email(html, f"[TEST] {subject}", recipients=test_to)
    elif not preview:
        send_email(html, subject)


if __name__ == "__main__":
    main()
