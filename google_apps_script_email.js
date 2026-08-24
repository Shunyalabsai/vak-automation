/**
 * Google Apps Script — Email Sender Web App
 *
 * This file is a REFERENCE for Google Apps Script (not executed locally).
 * Copy this code into a new Google Apps Script project at https://script.google.com
 *
 * Setup:
 * 1. Create a new Google Apps Script project
 * 2. Paste this code into Code.gs
 * 3. Deploy as Web App:
 *    - Click Deploy > New deployment
 *    - Type: Web app
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 4. Copy the Web App URL
 * 5. Add it as a GitHub repo secret: EMAIL_WEB_APP_URL
 *
 * How it works:
 * - Receives POST requests with { to, subject, body }
 * - Sends HTML email via MailApp.sendEmail()
 * - Returns JSON response { ok: true/false }
 */

function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents || "{}");
    var to = payload.to || "";
    var subject = payload.subject || "Vak API Automation Report";
    var body = payload.body || "";

    if (!to) {
      return ContentService.createTextOutput(
        JSON.stringify({ ok: false, error: "Missing recipient(s)." })
      ).setMimeType(ContentService.MimeType.JSON);
    }

    MailApp.sendEmail({
      to: to,
      subject: subject,
      htmlBody: body,
    });

    return ContentService.createTextOutput(
      JSON.stringify({ ok: true })
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(
      JSON.stringify({
        ok: false,
        error: error && error.message ? error.message : String(error),
      })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet() {
  return ContentService.createTextOutput(
    JSON.stringify({ ok: true, message: "Use POST to send email." })
  ).setMimeType(ContentService.MimeType.JSON);
}
