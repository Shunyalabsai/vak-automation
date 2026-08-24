/**
 * Google Apps Script — Scheduled Test Runner & Email Report
 *
 * This file is a REFERENCE for Google Apps Script (not executed locally).
 * Copy this code into a new Google Apps Script project at https://script.google.com
 *
 * Setup:
 * 1. Create a new Google Apps Script project
 * 2. Paste this code into Code.gs
 * 3. Go to Project Settings > Script Properties and add:
 *    - GITHUB_OWNER  → Shunyalabsai
 *    - GITHUB_REPO   → vak-automation
 *    - GITHUB_PAT    → your GitHub Personal Access Token (needs "repo" scope)
 * 4. Go to Triggers > Add Trigger:
 *
 *    Trigger 1 — Run Tests (scheduled):
 *      Function: triggerRunTests
 *      Event source: Time-driven
 *      Type: choose your frequency (e.g., every 6 hours)
 *
 *    IMPORTANT — avoid firing exactly at xx:58 IST:
 *    Several automations (Asksam, Website, Widget, Console, Zero Indic suites) are
 *    often scheduled on the same clock minute (:58). That aligns API load and causes
 *    intermittent failures on shared ASR/Translate/TTS backends. Prefer an odd minute
 *    offset for this repo (e.g. :03 or :17 past the hour) so Vak does not collide with
 *    the herd. The runner also staggers CI when it detects the xx:56–:01 IST window.
 *
 *    Trigger 2 — Send Email (scheduled, after tests):
 *      Function: triggerSendEmail
 *      Event source: Time-driven
 *      Type: Day timer → e.g., 6pm to 7pm
 *
 * How it works:
 * - triggerRunTests()   → dispatches GitHub Actions to run tests, update sheet & dashboard
 * - triggerSendEmail()  → dispatches GitHub Actions to send email report only
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

/** Trigger: Run tests + update sheet + update dashboard */
function triggerRunTests() {
  postDispatch("run-tests");
}

/** Trigger: Send email report only (uses latest test data) */
function triggerSendEmail() {
  postDispatch("send-email");
}

/**
 * Trigger: Send daily consolidated health report email.
 * Aggregates yesterday's test runs from ALL automation projects:
 *   - Asksam, Website, Widget, Console Dashboard, Vak BE
 *
 * Add a Time-driven trigger:
 *   Function: triggerDailyDigest
 *   Event source: Time-driven
 *   Type: Day timer → 9am to 10am (IST)
 */
function triggerDailyDigest() {
  postDispatch("daily-digest");
}

/**
 * Trigger: Send monthly downtime report (previous calendar month).
 * Runs on the 1st — e.g. 1 Jun emails the full May outage summary.
 *
 * Add a Time-driven trigger:
 *   Function: triggerMonthlyDowntime
 *   Event source: Time-driven
 *   Type: Month timer → 1st day of month, morning (e.g. 9am–10am IST)
 */
function triggerMonthlyDowntime() {
  postDispatch("monthly-downtime");
}
