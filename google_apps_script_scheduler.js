/**
 * Google Apps Script — Scheduled Test Runner & Health Reports
 *
 * Copy into your Scheduler Apps Script project at https://script.google.com
 *
 * Script properties:
 *   GITHUB_OWNER  → Shunyalabsai
 *   GITHUB_REPO   → vak-automation
 *   GITHUB_PAT    → classic token with repo scope
 *
 * ── Vak test schedule (IST) ──
 *   Morning batch: ~4:00–5:00 AM
 *   Evening batch: ~5:00–6:00 PM
 *
 * ── Triggers to add (Time-driven, timezone = Asia/Kolkata if available) ──
 *
 * 1) triggerRunTestsMorning
 *    Day timer → 4am to 5am   (runs Vak API tests after morning window starts)
 *
 * 2) triggerRunTestsEvening
 *    Day timer → 5pm to 6pm   (runs Vak API tests after evening window starts)
 *
 * 3) triggerDailyDigestMorning
 *    Day timer → 5am to 6am   (health email: start-of-day snapshot)
 *
 * 4) triggerDailyDigestEvening
 *    Day timer → 6pm to 7pm   (health email: end-of-day snapshot)
 *
 * 5) triggerMonthlyDowntime (optional)
 *    Month timer → 1st day, 9am–10am IST
 *
 * Health report covers: Widget, Console, Asksam.
 * (Vak BE, Playground QA, Meera QA, ASR/TTS Backend QA temporarily commented out.)
 * Vak triggers above only run tests for this repo; other repos need the same
 * morning/evening triggers in their own scheduler scripts.
 */

function postDispatch(eventType) {
  var props = PropertiesService.getScriptProperties();
  var owner = props.getProperty("GITHUB_OWNER");
  var repo = props.getProperty("GITHUB_REPO");
  var token = props.getProperty("GITHUB_PAT");

  if (!owner || !repo || !token) {
    throw new Error("Missing GITHUB_OWNER/GITHUB_REPO/GITHUB_PAT in script properties.");
  }

  var url = "https://api.github.com/repos/" + owner + "/" + repo + "/dispatches";
  var payload = JSON.stringify({ event_type: eventType });

  var options = {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: "token " + token,
      Accept: "application/vnd.github+json",
    },
    payload: payload,
    muteHttpExceptions: true,
  };

  var response = UrlFetchApp.fetch(url, options);
  if (response.getResponseCode() >= 300) {
    throw new Error("GitHub dispatch failed: " + response.getResponseCode() + " " + response.getContentText());
  }

  Logger.log("Dispatched '" + eventType + "' to " + owner + "/" + repo);
}

/** Vak API tests — morning batch */
function triggerRunTestsMorning() {
  postDispatch("run-tests");
}

/** Vak API tests — evening batch */
function triggerRunTestsEvening() {
  postDispatch("run-tests");
}

/** Legacy alias */
function triggerRunTests() {
  triggerRunTestsMorning();
}

/** Vak failure email only (optional; per-run emails fire from CI when tests fail) */
function triggerSendEmail() {
  postDispatch("send-email");
}

/** Twice-daily health digest — morning (after 4–5 AM project runs) */
function triggerDailyDigestMorning() {
  postDispatch("daily-digest-morning");
}

/** Twice-daily health digest — evening (after 5–6 PM project runs) */
function triggerDailyDigestEvening() {
  postDispatch("daily-digest-evening");
}

/** Legacy alias → morning digest */
function triggerDailyDigest() {
  triggerDailyDigestMorning();
}

/** Monthly downtime report — previous calendar month */
function triggerMonthlyDowntime() {
  postDispatch("monthly-downtime");
}
