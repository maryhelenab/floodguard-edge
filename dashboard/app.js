"use strict";

// Browser-only dashboard: reads the public API and updates the page safely.

// Runtime values are kept in config.js so deployment URLs are easy to change.
const CONFIG = window.FLOODGUARD_CONFIG;

// These zones match the simulator and query Lambda configuration.
const ZONES = [
  "dublin-zone-01",
  "dublin-zone-02",
  "dublin-zone-03",
  "dublin-zone-04"
];

// Numeric order makes risk levels easy to compare and sort.
const RISK_ORDER = {
  UNKNOWN: 0,
  INITIALISING: 1,
  NORMAL: 2,
  WATCH: 3,
  WARNING: 4,
  HIGH: 5,
  CRITICAL: 6
};

// Mutable page state is kept in one object to avoid scattered global variables.
const state = {
  selectedZone: ZONES[0],
  latestByZone: new Map(),
  errorsByZone: new Map(),
  charts: [],
  refreshing: false
};

// Cache DOM references once instead of searching the page on every refresh.
const el = {
  apiStatus: document.getElementById("api-status"),
  lastUpdate: document.getElementById("last-update"),
  refreshButton: document.getElementById("refresh-button"),
  message: document.getElementById("message"),
  zoneGrid: document.getElementById("zone-grid"),

  selectedZoneTitle: document.getElementById("selected-zone-title"),
  selectedZoneTime: document.getElementById("selected-zone-time"),
  riskBadge: document.getElementById("risk-badge"),
  noData: document.getElementById("no-data"),
  zoneDetails: document.getElementById("zone-details"),

  riskScore: document.getElementById("risk-score"),
  reasonsList: document.getElementById("reasons-list"),
  recommendedAction: document.getElementById("recommended-action"),

  rainfall: document.getElementById("rainfall"),
  waterLevel: document.getElementById("water-level"),
  flowRate: document.getElementById("flow-rate"),
  soilSaturation: document.getElementById("soil-saturation"),
  drainBlockage: document.getElementById("drain-blockage"),

  riskChart: document.getElementById("risk-chart"),
  rainfallChart: document.getElementById("rainfall-chart"),
  waterChart: document.getElementById("water-chart"),
  historyEmpty: document.getElementById("history-empty"),

  alertsList: document.getElementById("alerts-list")
};

// Fetch one API route with timeout, JSON validation, and friendly errors.
async function fetchJson(path) {
  // AbortController stops a request that exceeds the configured timeout.
  const controller = new AbortController();

  const timeoutId = setTimeout(
    () => controller.abort(),
    CONFIG.REQUEST_TIMEOUT_MS
  );

  try {
    const response = await fetch(`${CONFIG.API_BASE_URL}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal
    });

    const text = await response.text();
    let data = null;

    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error("The API returned invalid JSON.");
      }
    }

    if (!response.ok) {
      const error = new Error(
        data?.message || `HTTP ${response.status}`
      );
      error.status = response.status;
      throw error;
    }

    return data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The API request timed out.");
    }

    if (error instanceof TypeError) {
      throw new Error("The FloodGuard API could not be reached.");
    }

    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

// Return a safe payload object even when an API record is missing.
function payload(record) {
  return record && typeof record.payload === "object"
    ? record.payload
    : {};
}

// Accept only known risk labels before using a value in CSS class names.
function risk(value) {
  const level = String(value || "UNKNOWN").toUpperCase();
  return Object.hasOwn(RISK_ORDER, level) ? level : "UNKNOWN";
}

// Format sensor values consistently and show an em dash for missing data.
function number(value) {
  if (value === null || value === undefined) {
    return "—";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : "—";
}

// Display timestamps using Irish date and time conventions.
function dateTime(value) {
  const date = new Date(value);

  if (!value || Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("en-IE", {
    timeZone: "Europe/Dublin",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date);
}

// Use a compact date and time label on chart axes.
function chartDateTime(value) {
  const date = new Date(value);

  if (!value || Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("en-IE", {
    timeZone: "Europe/Dublin",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date);
}

// Explain how old the latest stored event is.
function eventAge(value) {
  const eventTime = new Date(value).getTime();

  if (!value || Number.isNaN(eventTime)) {
    return "";
  }

  const differenceMs = Date.now() - eventTime;

  if (differenceMs < 0) {
    return "event time is ahead of the dashboard clock";
  }

  const minutes = Math.floor(differenceMs / 60000);

  if (minutes < 1) {
    return "just now";
  }

  if (minutes < 60) {
    return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  }

  const hours = Math.floor(minutes / 60);

  if (hours < 24) {
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }

  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

// API records can contain time in the payload or in stored metadata.
function recordTime(record, payloadField) {
  return payload(record)[payloadField]
    || record?.event_time
    || record?.received_at
    || null;
}

// Remove existing children before re-rendering a dynamic section.
function clear(element) {
  while (element.firstChild) {
    element.removeChild(element.firstChild);
  }
}

// Create text-only DOM nodes; textContent avoids injecting HTML from API data.
function make(tag, text, className = "") {
  const element = document.createElement(tag);
  element.textContent = text;

  if (className) {
    element.className = className;
  }

  return element;
}

// Apply both the text and matching colour class for one risk badge.
function setBadge(element, level) {
  const safeRisk = risk(level);
  element.className = `risk-badge risk-${safeRisk.toLowerCase()}`;
  element.textContent = safeRisk;
}

function showMessage(text) {
  el.message.textContent = text;
  el.message.hidden = false;
}

function hideMessage() {
  el.message.hidden = true;
}

// Load every zone in parallel so one failed zone does not block the others.
async function loadLatestStatuses() {
  const requests = ZONES.map((zone) =>
    fetchJson(`/zones/${encodeURIComponent(zone)}/latest`)
  );

  // allSettled preserves successful results when some requests fail.
  const results = await Promise.allSettled(requests);

  state.latestByZone.clear();
  state.errorsByZone.clear();

  results.forEach((result, index) => {
    const zone = ZONES[index];

    if (result.status === "fulfilled") {
      state.latestByZone.set(zone, result.value);
    } else {
      state.errorsByZone.set(zone, result.reason);
    }
  });
}

// Convert request state into a short message for the zone card.
function zoneAvailability(zone) {
  if (state.latestByZone.has(zone)) {
    return "Data available";
  }

  if (state.errorsByZone.get(zone)?.status === 404) {
    return "No data";
  }

  return "Temporarily unavailable";
}

// Build the selectable overview card for each monitored zone.
function renderZones() {
  clear(el.zoneGrid);

  ZONES.forEach((zone) => {
    const record = state.latestByZone.get(zone);
    const data = payload(record);
    const currentRisk = record ? risk(data.risk_level) : "UNKNOWN";

    const card = document.createElement("article");
    card.className = "card zone-card";
    card.tabIndex = 0;

    if (zone === state.selectedZone) {
      card.classList.add("selected");
    }

    card.appendChild(make("h3", zone));
    card.appendChild(
      make(
        "span",
        currentRisk,
        `risk-badge risk-${currentRisk.toLowerCase()}`
      )
    );

    card.appendChild(
      make(
        "p",
        `Risk score: ${record ? number(data.risk_score) : "—"}`
      )
    );

    card.appendChild(
      make("p", zoneAvailability(zone))
    );

    const button = make(
      "button",
      zone === state.selectedZone ? "Selected" : "View zone"
    );

    button.type = "button";
    button.addEventListener("click", () => selectZone(zone));

    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectZone(zone);
      }
    });

    card.appendChild(button);
    el.zoneGrid.appendChild(card);
  });
}

// Show the human-readable reasons returned by the fog risk engine.
function renderReasons(reasons) {
  clear(el.reasonsList);

  const items = Array.isArray(reasons) ? reasons : [];

  if (items.length === 0) {
    el.reasonsList.appendChild(
      make("li", "No reasons available.")
    );
    return;
  }

  items.forEach((item) => {
    el.reasonsList.appendChild(make("li", String(item)));
  });
}

// Fill the current-risk and latest-sensor section for the selected zone.
function renderCurrentZone() {
  const record = state.latestByZone.get(state.selectedZone);

  el.selectedZoneTitle.textContent = state.selectedZone;

  if (!record) {
    el.zoneDetails.hidden = true;
    el.noData.hidden = false;
    el.noData.textContent =
      state.errorsByZone.get(state.selectedZone)?.status === 404
        ? "No monitoring data is available for this zone."
        : "This zone is temporarily unavailable.";

    el.selectedZoneTime.textContent = "No current event time.";
    setBadge(el.riskBadge, "UNKNOWN");
    return;
  }

  const data = payload(record);
  const sensors = data.sensor_snapshot || {};

  el.noData.hidden = true;
  el.zoneDetails.hidden = false;

  const latestEventTime = recordTime(record, "computed_at");
  const latestEventAge = eventAge(latestEventTime);

  el.selectedZoneTime.textContent =
    `Latest data received: ${dateTime(latestEventTime)}` +
    (latestEventAge ? ` (${latestEventAge})` : "");

  setBadge(el.riskBadge, data.risk_level);

  el.riskScore.textContent = number(data.risk_score);
  renderReasons(data.reasons);

  el.rainfall.textContent = number(sensors.rainfall);
  el.waterLevel.textContent = number(sensors.water_level);
  el.flowRate.textContent = number(sensors.flow_rate);
  el.soilSaturation.textContent = number(sensors.soil_saturation);
  el.drainBlockage.textContent = number(sensors.drain_blockage);
}

// Chart.js instances must be destroyed before the same canvas is reused.
function destroyCharts() {
  state.charts.forEach((chart) => chart.destroy());
  state.charts = [];
}

// Create one small line chart with the common dashboard options.
function createLineChart(
  canvas,
  title,
  labels,
  values,
  yLabel,
  timestamps,
  historySummary
) {
  return new window.Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: title,
        data: values,
        borderColor: "#176b87",
        backgroundColor: "rgba(23, 107, 135, 0.12)",
        borderWidth: 2,
        tension: 0.2,
        fill: true
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: {
          display: true,
          text: title
        },
        subtitle: {
          display: true,
          text: historySummary,
          padding: {
            bottom: 12
          }
        },
        tooltip: {
          callbacks: {
            title(tooltipItems) {
              const index = tooltipItems[0]?.dataIndex;
              return dateTime(timestamps[index]);
            }
          }
        }
      },
      scales: {
        x: {
          title: {
            display: true,
            text: "Recorded event date and time"
          }
        },
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: yLabel
          }
        }
      }
    }
  });
}

// Convert recent status records into chronologically ordered chart series.
function renderHistory(items) {
  destroyCharts();

  const rows = (Array.isArray(items) ? items : [])
  .filter((item) => {
    const itemPayload = payload(item);
    return itemPayload.risk_score !== null
      && itemPayload.risk_score !== undefined;
  })
    .sort(
      (a, b) =>
        new Date(recordTime(a, "computed_at")) -
        new Date(recordTime(b, "computed_at"))
    );

  if (rows.length === 0 || typeof window.Chart !== "function") {
    el.historyEmpty.hidden = false;
    return;
  }

  el.historyEmpty.hidden = true;

  const timestamps = rows.map(
    (item) => recordTime(item, "computed_at")
  );

  const labels = timestamps.map(chartDateTime);

  const firstTimestamp = timestamps[0];
  const lastTimestamp = timestamps[timestamps.length - 1];

  const historySummary = [
    `Latest ${rows.length} recorded status event${rows.length === 1 ? "" : "s"} (not a fixed hourly window)`,
    `${dateTime(firstTimestamp)} — ${dateTime(lastTimestamp)}`
  ];

  const riskScores = rows.map(
    (item) => Number(payload(item).risk_score)
  );

  const rainfallValues = rows.map(
    (item) => Number(payload(item).sensor_snapshot?.rainfall)
  );

  const waterValues = rows.map(
    (item) => Number(payload(item).sensor_snapshot?.water_level)
  );

  state.charts.push(
    createLineChart(
      el.riskChart,
      "Risk score history",
      labels,
      riskScores,
      "Risk score",
      timestamps,
      historySummary
    )
  );

  state.charts.push(
    createLineChart(
      el.rainfallChart,
      "Rainfall history",
      labels,
      rainfallValues,
      "Rainfall (mm/h)",
      timestamps,
      historySummary
    )
  );

  state.charts.push(
    createLineChart(
      el.waterChart,
      "Water level history",
      labels,
      waterValues,
      "Water level (cm)",
      timestamps,
      historySummary
    )
  );
}

// Render newest alerts first and highlight HIGH/CRITICAL records.
function renderAlerts(items) {
  clear(el.alertsList);

  const rows = (Array.isArray(items) ? items : [])
    .sort(
      (a, b) =>
        new Date(recordTime(b, "triggered_at")) -
        new Date(recordTime(a, "triggered_at"))
    )
    .slice(0, 5);

  if (rows.length === 0) {
    el.alertsList.appendChild(
      make("p", "No alerts recorded.", "card empty-state")
    );
    el.recommendedAction.textContent =
      "No recommendation available.";
    return;
  }

  rows.forEach((item) => {
    const data = payload(item);
    const severity = risk(data.severity);

    const card = document.createElement("article");
    card.className = "card alert-card";

    if (severity === "HIGH") {
      card.classList.add("high");
    }

    if (severity === "CRITICAL") {
      card.classList.add("critical");
    }

    card.appendChild(
      make("h3", `${severity} \u2014 ${number(data.risk_score)}`)
    );

    card.appendChild(
      make("p", dateTime(recordTime(item, "triggered_at")))
    );

    card.appendChild(
      make("p", data.message || "No message.")
    );

    card.appendChild(
      make(
        "p",
        `Action: ${data.recommended_action || "No recommendation."}`
      )
    );

    el.alertsList.appendChild(card);
  });

  el.recommendedAction.textContent =
    payload(rows[0]).recommended_action
    || "No recommendation available.";
}

// Fetch history and alerts together for the selected zone.
async function loadSelectedZoneData(zone) {
  const encoded = encodeURIComponent(zone);

  const [historyResult, alertsResult] = await Promise.allSettled([
    fetchJson(`/zones/${encoded}/history?limit=20`),
    fetchJson(`/zones/${encoded}/alerts?limit=20`)
  ]);

  // Ignore a slow response if the user selected another zone meanwhile.
  if (state.selectedZone !== zone) {
    return;
  }

  if (historyResult.status === "fulfilled") {
    renderHistory(historyResult.value?.items);
  } else {
    renderHistory([]);
  }

  if (alertsResult.status === "fulfilled") {
    renderAlerts(alertsResult.value?.items);
  } else {
    renderAlerts([]);
  }
}

// Update selection immediately, then load the zone-specific data.
function selectZone(zone) {
  state.selectedZone = zone;
  renderZones();
  renderCurrentZone();

  loadSelectedZoneData(zone).catch((error) => {
    showMessage(error.message);
  });
}

// Run one complete health, latest-status, history, and alert refresh.
async function refreshDashboard() {
  // Prevent overlapping refreshes from the timer and refresh button.
  if (state.refreshing) {
    return;
  }

  state.refreshing = true;
  el.refreshButton.disabled = true;
  hideMessage();

  try {
    const healthResult = await Promise.allSettled([
      fetchJson("/health")
    ]);

    const healthOk =
      healthResult[0].status === "fulfilled"
      && healthResult[0].value?.status === "healthy";

    el.apiStatus.textContent =
      healthOk ? "API connection: Healthy" : "API connection: Unavailable";

    el.apiStatus.className =
      healthOk ? "healthy" : "error";

    await loadLatestStatuses();

    renderZones();
    renderCurrentZone();
    await loadSelectedZoneData(state.selectedZone);

    const now = new Date();
    el.lastUpdate.textContent = dateTime(now);

    if (state.errorsByZone.size > 0) {
      showMessage(
        `${state.errorsByZone.size} zone request(s) failed, but the other zones still loaded.`
      );
    }
  } catch (error) {
    el.apiStatus.textContent = "API connection: Unavailable";
    el.apiStatus.className = "error";
    showMessage(error.message || "The dashboard could not be refreshed.");
  } finally {
    state.refreshing = false;
    el.refreshButton.disabled = false;
  }
}

// Manual refresh uses the same safe workflow as automatic refresh.
el.refreshButton.addEventListener("click", refreshDashboard);

// Load immediately, then repeat at the configured interval.
refreshDashboard().finally(() => {
  setInterval(refreshDashboard, CONFIG.REFRESH_INTERVAL_MS);
});
