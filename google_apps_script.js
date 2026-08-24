/**
 * Google Apps Script — Vak API Test Reporter with Audio Playback
 *
 * Audio playback: stores audio in a hidden sheet, serves HTML player via doGet.
 * NO Drive permission needed.
 */

// ── Sheet names ──
var INDIVIDUAL_SHEET = "Individual Tests";
var PIPELINE_SHEET = "Pipeline Tests";
var SUMMARY_SHEET = "Summary";
var AUDIO_STORE_SHEET = "_AudioStore";

var CHUNK_SIZE = 49000;

// ── Column headers (different for Individual vs Pipeline) ──
var INDIVIDUAL_HEADERS = [
  "Timestamp",
  "Endpoint",
  "Test Name",
  "Input",
  "Source Lang",
  "Target Lang",
  "Output",
  "Status",
  "Latency (ms)",
  "Output Size",
  "Notes / Error"
];

var PIPELINE_HEADERS = [
  "Timestamp",
  "Audio File",
  "Source Lang",
  "Target Lang",
  "ASR Text",
  "Translated Text",
  "TTS Output",
  "Status",
  "ASR Latency (ms)",
  "Translate Latency (ms)",
  "TTS Latency (ms)",
  "Total Latency (ms)",
  "TTS Size",
  "Notes / Error"
];

/** doGet — serves audio player page */
function doGet(e) {
  var audioId = e.parameter.play;
  if (!audioId) {
    return HtmlService.createHtmlOutput("<h2>Vak Test Audio Player</h2><p>No audio ID provided.</p>");
  }

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var store = ss.getSheetByName(AUDIO_STORE_SHEET);
  if (!store) {
    return HtmlService.createHtmlOutput("<h2>Error</h2><p>Audio store not found.</p>");
  }

  var data = store.getDataRange().getValues();
  var audioB64 = "";
  var filename = "";

  for (var i = 0; i < data.length; i++) {
    if (data[i][0] === audioId) {
      filename = data[i][1] || "audio.wav";
      for (var j = 2; j < data[i].length; j++) {
        if (data[i][j]) audioB64 += data[i][j];
      }
      break;
    }
  }

  if (!audioB64) {
    return HtmlService.createHtmlOutput("<h2>Error</h2><p>Audio not found for ID: " + audioId + "</p>");
  }

  var html = '<!DOCTYPE html><html><head><title>Vak Audio: ' + filename + '</title>'
    + '<style>'
    + 'body { font-family: -apple-system, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 80vh; background: #f5f5f5; margin: 0; }'
    + '.card { background: white; border-radius: 12px; padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }'
    + 'h2 { color: #333; margin-bottom: 8px; }'
    + 'p { color: #666; margin-bottom: 24px; }'
    + 'audio { width: 100%; }'
    + '</style></head><body>'
    + '<div class="card">'
    + '<h2>&#127925; ' + filename + '</h2>'
    + '<p>Vak API Test Output</p>'
    + '<audio controls autoplay><source src="data:audio/wav;base64,' + audioB64 + '" type="audio/wav">Your browser does not support audio.</audio>'
    + '</div></body></html>';

  return HtmlService.createHtmlOutput(html)
    .setTitle("Vak Audio: " + filename)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/** Store audio in hidden sheet, return audio ID */
function storeAudio(ss, base64Data, filename) {
  if (!base64Data || base64Data.length === 0) return "";

  var store = ss.getSheetByName(AUDIO_STORE_SHEET);
  if (!store) {
    store = ss.insertSheet(AUDIO_STORE_SHEET);
    store.hideSheet();
  }

  var audioId = Utilities.getUuid().substring(0, 8);
  var chunks = [];
  for (var i = 0; i < base64Data.length; i += CHUNK_SIZE) {
    chunks.push(base64Data.substring(i, i + CHUNK_SIZE));
  }

  store.appendRow([audioId, filename].concat(chunks));
  return audioId;
}

/** Handle POST from Python */
function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);
    var results = payload.results;
    var scriptUrl = payload.script_url || "";

    if (!results || results.length === 0) {
      return ContentService.createTextOutput(
        JSON.stringify({ status: "error", message: "No results provided" })
      ).setMimeType(ContentService.MimeType.JSON);
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var individualRows = [];
    var pipelineRows = [];

    results.forEach(function (r) {
      var audioLink = "";
      if (r.audio_b64 && r.audio_b64.length > 0) {
        var fname = r.audio_filename || "audio.wav";
        var audioId = storeAudio(ss, r.audio_b64, fname);
        if (audioId && scriptUrl) {
          audioLink = scriptUrl + "?play=" + audioId;
        }
      }

      if (r.test_type === "Pipeline") {
        pipelineRows.push({
          data: [
            r.timestamp || "",
            r.input || "",
            r.source_lang || "",
            r.target_lang || "",
            r.asr_text || "",
            r.translated_text || "",
            r.tts_file || "",
            r.status || "",
            r.asr_latency_ms || "",
            r.translate_latency_ms || "",
            r.tts_latency_ms || "",
            r.latency_ms || "",
            r.output_size || "",
            r.error || ""
          ],
          audioLink: audioLink
        });
      } else {
        individualRows.push({
          data: [
            r.timestamp || "",
            r.endpoint || "",
            r.test_name || "",
            r.input || "",
            r.source_lang || "",
            r.target_lang || "",
            r.output || "",
            r.status || "",
            r.latency_ms || "",
            r.output_size || "",
            r.error || ""
          ],
          audioLink: audioLink
        });
      }
    });

    if (individualRows.length > 0) {
      var indSheet = getOrCreateSheet(ss, INDIVIDUAL_SHEET, INDIVIDUAL_HEADERS);
      var outputCol = INDIVIDUAL_HEADERS.indexOf("Output") + 1;  // col 7
      writeRows(indSheet, individualRows, INDIVIDUAL_HEADERS, outputCol);
    }

    if (pipelineRows.length > 0) {
      var pipSheet = getOrCreateSheet(ss, PIPELINE_SHEET, PIPELINE_HEADERS);
      var ttsCol = PIPELINE_HEADERS.indexOf("TTS Output") + 1;  // col 7
      writeRows(pipSheet, pipelineRows, PIPELINE_HEADERS, ttsCol);
    }

    updateSummary(ss, results);

    return ContentService.createTextOutput(
      JSON.stringify({
        status: "success",
        individual_rows: individualRows.length,
        pipeline_rows: pipelineRows.length
      })
    ).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({ status: "error", message: err.toString() })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

/** Get existing sheet or create only if it doesn't exist. Never deletes user-formatted sheets. */
function getOrCreateSheet(ss, name, headers) {
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.getRange(1, 1, 1, headers.length).setFontWeight("bold");
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, headers.length).setBackground("#4a86c8").setFontColor("#ffffff");
  }
  return sheet;
}

/** Write rows with formatting. Clears old data rows (keeps header), writes fresh. */
function writeRows(sheet, rowObjects, headers, audioLinkCol) {
  // Clear all data rows below header (row 1), keep header + formatting
  var lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    sheet.getRange(2, 1, lastRow - 1, sheet.getMaxColumns()).clearContent();
    sheet.getRange(2, 1, lastRow - 1, sheet.getMaxColumns()).clearFormat();
  }

  var startRow = 2;
  var statusCol = headers.indexOf("Status") + 1;

  // Extract plain data arrays
  var dataRows = rowObjects.map(function (r) { return r.data; });
  sheet.getRange(startRow, 1, dataRows.length, headers.length).setValues(dataRows);

  for (var i = 0; i < rowObjects.length; i++) {
    var rowIdx = startRow + i;

    // Color status
    if (statusCol > 0) {
      var statusCell = sheet.getRange(rowIdx, statusCol);
      var statusVal = dataRows[i][statusCol - 1];
      if (statusVal === "PASS") {
        statusCell.setBackground("#d4edda").setFontColor("#155724");
      } else if (statusVal === "FAIL") {
        statusCell.setBackground("#f8d7da").setFontColor("#721c24");
      }
    }

    // Make filename clickable in the Output/TTS Output cell
    var audioUrl = rowObjects[i].audioLink;
    if (audioUrl && audioUrl.length > 0 && audioLinkCol > 0) {
      var cell = sheet.getRange(rowIdx, audioLinkCol);
      var fileName = dataRows[i][audioLinkCol - 1] || "audio.wav";
      var richText = SpreadsheetApp.newRichTextValue()
        .setText(fileName)
        .setLinkUrl(audioUrl)
        .build();
      cell.setRichTextValue(richText);
      cell.setFontColor("#1155cc");
    }
  }
}

/** Update Summary sheet */
function updateSummary(ss, results) {
  var sheet = ss.getSheetByName(SUMMARY_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(SUMMARY_SHEET);
    ss.setActiveSheet(sheet);
    ss.moveActiveSheet(1);
  }

  var totalTests = results.length;
  var passed = results.filter(function (r) { return r.status === "PASS"; }).length;
  var failed = results.filter(function (r) { return r.status === "FAIL"; }).length;
  var passRate = totalTests > 0 ? ((passed / totalTests) * 100).toFixed(1) + "%" : "N/A";
  var timestamp = results[0] ? results[0].timestamp : "N/A";

  var endpoints = {};
  results.forEach(function (r) {
    var key = r.endpoint || "Unknown";
    if (!endpoints[key]) endpoints[key] = { pass: 0, fail: 0, total: 0 };
    endpoints[key].total++;
    if (r.status === "PASS") endpoints[key].pass++;
    else endpoints[key].fail++;
  });

  var latencies = {};
  results.forEach(function (r) {
    var key = r.endpoint || "Unknown";
    if (!latencies[key]) latencies[key] = [];
    if (r.latency_ms) latencies[key].push(parseFloat(r.latency_ms));
  });

  sheet.clear();

  var summaryData = [
    ["VAK API Test Report", "", "", ""],
    ["", "", "", ""],
    ["Last Run", timestamp, "", ""],
    ["Total Tests", totalTests, "", ""],
    ["Passed", passed, "", ""],
    ["Failed", failed, "", ""],
    ["Pass Rate", passRate, "", ""],
    ["", "", "", ""],
    ["Endpoint Breakdown", "Total", "Passed", "Failed", "Avg Latency (ms)"],
  ];

  Object.keys(endpoints).forEach(function (key) {
    var avgLat = "-";
    if (latencies[key] && latencies[key].length > 0) {
      var sum = latencies[key].reduce(function (a, b) { return a + b; }, 0);
      avgLat = (sum / latencies[key].length).toFixed(1);
    }
    summaryData.push([key, endpoints[key].total, endpoints[key].pass, endpoints[key].fail, avgLat]);
  });

  sheet.getRange(1, 1, summaryData.length, 5).setValues(
    summaryData.map(function (row) {
      while (row.length < 5) row.push("");
      return row;
    })
  );

  sheet.getRange(1, 1).setFontSize(16).setFontWeight("bold");
  sheet.getRange(3, 1, 5, 1).setFontWeight("bold");
  sheet.getRange(9, 1, 1, 5).setFontWeight("bold").setBackground("#4a86c8").setFontColor("#ffffff");
  sheet.setColumnWidth(1, 200);
  sheet.setColumnWidth(2, 120);
}

function setupSheets() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  getOrCreateSheet(ss, INDIVIDUAL_SHEET, INDIVIDUAL_HEADERS);
  getOrCreateSheet(ss, PIPELINE_SHEET, PIPELINE_HEADERS);
}
