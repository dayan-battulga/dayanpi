// The stats stream, the Pi tiles and status bar, the theme toggle and the camera.
// focus.js draws the Focus card from the same stream (see "dayanpi:snapshot").

const TEMP_ELEVATED_C = 70;
const TEMP_CRITICAL_C = 80;
const GAUGE_MIN_C = 20;
const GAUGE_MAX_C = 85;
const LOAD_ELEVATED_PCT = 70;
const LOAD_CRITICAL_PCT = 90;
const BLOCK_COUNT = 20;
const MIN_CORE_SHARE = 4; // % of the bar, so an idle core still shows a sliver
const THEME_FADE_MS = 700;
const FEED_RETRY_BASE_MS = 2000; // 2, 4, 8, 16 s...
const FEED_RETRY_MAX_MS = 30000; // ...then every 30 s
const FEED_STABLE_MS = 30000; // up this long = healthy again, back to 2 s
const BLANK_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
const STATUS_LABELS = {
  connected: "Live",
  reconnecting: "Reconnecting",
  disconnected: "Offline",
};

const els = {
  status: document.getElementById("status"),
  statusLabel: document.querySelector("#status .status-label"),
  powerAlert: document.getElementById("power-alert"),
  themeToggle: document.getElementById("theme-toggle"),
  piSummary: document.getElementById("pi-summary"),
  temp: document.getElementById("temp"),
  tempArc: document.getElementById("temp-arc"),
  cpu: document.getElementById("cpu"),
  cpuCores: document.getElementById("cpu-cores"),
  cpuCoresLabel: document.getElementById("cpu-cores-label"),
  memPercent: document.getElementById("mem-percent"),
  memDetail: document.getElementById("mem-detail"),
  memBlocks: document.getElementById("mem-blocks"),
  diskPercent: document.getElementById("disk-percent"),
  diskDetail: document.getElementById("disk-detail"),
  diskBlocks: document.getElementById("disk-blocks"),
  net: document.getElementById("net"),
  uptime: document.getElementById("uptime"),
  power: document.getElementById("power"),
  camera: document.getElementById("camera"),
  cameraStatus: document.getElementById("camera-status"),
  feed: document.getElementById("feed"),
  peekToggle: document.getElementById("peek-toggle"),
  peekLabel: document.getElementById("peek-label"),
};

let events = null;
let themeFadeTimer = null;
let feedWanted = false;
let feedFailures = 0;
let feedRetryTimer = null;
let feedStableTimer = null;

// ---------- connection ----------

function setStatus(state) {
  els.status.dataset.state = state;
  els.statusLabel.textContent = STATUS_LABELS[state] ?? state;
}

function startEvents() {
  if (events == null) {
    events = new EventSource("/api/stream");
    events.onmessage = (event) => {
      const sample = JSON.parse(event.data);
      renderStats(sample);
      setStatus("connected");
      // focus.js listens for this instead of opening a second stream.
      window.dispatchEvent(new CustomEvent("dayanpi:snapshot", { detail: sample }));
    };
    // The browser reconnects by itself; only the indicator needs updating.
    events.onerror = () => {
      setStatus("reconnecting");
    };
  }
}

function stopEvents() {
  if (events != null) {
    events.close();
    events = null;
  }
}

// ---------- Pi tiles and status bar ----------

function readLevel(value, elevatedAt, criticalAt) {
  let level = "nominal";
  if (value >= criticalAt) {
    level = "critical";
  } else if (value >= elevatedAt) {
    level = "elevated";
  }
  return level;
}

function buildBlocks(container) {
  for (let index = 0; index < BLOCK_COUNT; index += 1) {
    const block = document.createElement("span");
    block.className = "blk";
    container.append(block);
  }
}

function setBlocks(container, percent, level) {
  const clamped = Math.max(0, Math.min(100, percent));
  const filled = Math.round((clamped / 100) * BLOCK_COUNT);
  container.dataset.level = level;
  container.setAttribute("aria-valuenow", String(Math.round(clamped)));
  container.querySelectorAll(".blk").forEach((block, index) => {
    block.classList.toggle("on", index < filled);
  });
}

function setCoreBars(percents) {
  if (els.cpuCores.children.length !== percents.length) {
    const bars = percents.map(() => {
      const core = document.createElement("span");
      const fill = document.createElement("span");
      core.className = "core";
      fill.className = "core-fill";
      core.append(fill);
      return core;
    });
    els.cpuCores.replaceChildren(...bars);
  }
  percents.forEach((percent, index) => {
    const fill = els.cpuCores.children[index].firstElementChild;
    fill.style.height = `${Math.max(MIN_CORE_SHARE, Math.min(100, percent))}%`;
    fill.dataset.level = readLevel(percent, LOAD_ELEVATED_PCT, LOAD_CRITICAL_PCT);
  });
  const described = percents.map((percent) => `${Math.round(percent)}%`).join(", ");
  els.cpuCores.setAttribute("aria-label", percents.length > 0 ? `Per core: ${described}` : "Per-core load not available yet");
  els.cpuCoresLabel.textContent = percents.length > 0 ? `${percents.length} cores` : "all cores";
}

function formatUptime(seconds) {
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const text = `${days}d ${hours}h ${minutes}m`;
  return text;
}

function formatBits(kbps) {
  const text = kbps >= 1000 ? `${(kbps / 1000).toFixed(1)} Mb/s` : `${Math.round(kbps)} kb/s`;
  return text;
}

function describePower(throttle) {
  const live = [];
  const sticky = [];
  if (throttle.is_undervoltage) {
    live.push("undervoltage");
  }
  if (throttle.is_frequency_capped) {
    live.push("freq capped");
  }
  if (throttle.is_throttled) {
    live.push("throttled");
  }
  if (throttle.has_undervoltage_occured) {
    sticky.push("undervoltage");
  }
  if (throttle.has_throttling_occured) {
    sticky.push("throttling");
  }
  const power = { text: "all clear", level: "nominal", live: live.length > 0 };
  if (live.length > 0) {
    power.text = `now: ${live.join(", ")}`;
    power.level = "critical";
  } else if (sticky.length > 0) {
    power.text = `since boot: ${sticky.join(", ")}`;
    power.level = "elevated";
  }
  return power;
}

function describePi(stats, power) {
  const cpu = stats.rates == null ? 0 : stats.rates.cpu_percent;
  const summary = { text: "Running smooth", level: "nominal" };
  if (power.live) {
    summary.text = "Power problem";
    summary.level = "critical";
  } else if (stats.temperature_celsius >= TEMP_CRITICAL_C) {
    summary.text = "Running hot";
    summary.level = "critical";
  } else if (stats.temperature_celsius >= TEMP_ELEVATED_C) {
    summary.text = "Running warm";
    summary.level = "elevated";
  } else if (cpu >= LOAD_CRITICAL_PCT) {
    summary.text = "Working hard";
    summary.level = "elevated";
  }
  return summary;
}

function renderStats(stats) {
  const temp = stats.temperature_celsius;
  const tempLevel = readLevel(temp, TEMP_ELEVATED_C, TEMP_CRITICAL_C);
  const gaugeShare = ((temp - GAUGE_MIN_C) / (GAUGE_MAX_C - GAUGE_MIN_C)) * 100;
  setText(els.temp, temp.toFixed(1));
  els.temp.dataset.level = tempLevel;
  els.tempArc.dataset.level = tempLevel;
  els.tempArc.style.strokeDasharray = `${Math.max(0, Math.min(100, gaugeShare)).toFixed(1)} 100`;

  if (stats.rates == null) {
    setText(els.cpu, "--");
    els.cpu.dataset.level = "nominal";
    setCoreBars([]);
    setText(els.net, "--");
  } else {
    const cpu = stats.rates.cpu_percent;
    setText(els.cpu, Math.round(cpu));
    els.cpu.dataset.level = readLevel(cpu, LOAD_ELEVATED_PCT, LOAD_CRITICAL_PCT);
    setCoreBars(stats.rates.core_percents ?? []);
    setText(els.net, `↓ ${formatBits(stats.rates.rx_kbps)} · ↑ ${formatBits(stats.rates.tx_kbps)}`);
  }

  const memory = stats.memory;
  const usedGb = (memory.total_mb - memory.available_mb) / 1024;
  setText(els.memPercent, Math.round(memory.percent_used));
  setText(els.memDetail, `${usedGb.toFixed(1)} / ${(memory.total_mb / 1024).toFixed(1)} GB`);
  setBlocks(els.memBlocks, memory.percent_used, readLevel(memory.percent_used, LOAD_ELEVATED_PCT, LOAD_CRITICAL_PCT));

  const disk = stats.disk;
  setText(els.diskPercent, Math.round(disk.percent_used));
  setText(els.diskDetail, `${disk.free_gb.toFixed(1)} GB free`);
  setBlocks(els.diskBlocks, disk.percent_used, readLevel(disk.percent_used, LOAD_ELEVATED_PCT, LOAD_CRITICAL_PCT));

  setText(els.uptime, formatUptime(stats.uptime_seconds));

  const power = describePower(stats.throttle);
  setText(els.power, power.text);
  els.power.dataset.level = power.level;
  els.powerAlert.hidden = !stats.throttle.is_undervoltage;

  const summary = describePi(stats, power);
  setText(els.piSummary, summary.text);
  els.piSummary.dataset.level = summary.level;
}

// ---------- theme ----------

function applyTheme(theme, fade) {
  const root = document.documentElement;
  if (fade) {
    root.classList.add("theme-fade");
    clearTimeout(themeFadeTimer);
    themeFadeTimer = setTimeout(() => root.classList.remove("theme-fade"), THEME_FADE_MS);
  }
  root.dataset.theme = theme;
  els.themeToggle.setAttribute("aria-label", theme === "dark" ? "Switch to light mode" : "Switch to dark mode");
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  writeStored("theme", next);
  applyTheme(next, true);
}

function followSystemTheme(event) {
  if (readStored("theme", null) === null) {
    applyTheme(event.matches ? "dark" : "light", true);
  }
}

// ---------- camera ----------

function setCameraStatus(text) {
  els.cameraStatus.textContent = text;
}

// Swapping the src for a blank image is what actually closes the MJPEG connection.
function stopFeed() {
  clearTimeout(feedRetryTimer);
  clearTimeout(feedStableTimer);
  feedStableTimer = null;
  els.camera.classList.remove("is-live");
  els.feed.src = BLANK_IMAGE;
}

function setPeek(peeking) {
  feedWanted = peeking;
  els.camera.classList.toggle("is-peeking", peeking);
  els.peekLabel.textContent = peeking ? "Hide" : "Peek";
  els.peekToggle.setAttribute("aria-pressed", String(peeking));
  if (peeking) {
    setCameraStatus("connecting…");
    els.feed.src = `/video?t=${Date.now()}`;
  } else {
    stopFeed();
    setCameraStatus("hidden · nothing saved");
  }
}

// /video's rate limit is shared by every viewer, so back off instead of
// burning through it with fixed 2 s retries.
function handleFeedError() {
  if (feedWanted) {
    els.camera.classList.remove("is-live");
    setCameraStatus("reconnecting…");
    clearTimeout(feedStableTimer);
    feedStableTimer = null;
    const retryDelay = Math.min(FEED_RETRY_BASE_MS * 2 ** feedFailures, FEED_RETRY_MAX_MS);
    feedFailures += 1;
    clearTimeout(feedRetryTimer);
    feedRetryTimer = setTimeout(() => {
      if (feedWanted) {
        els.feed.src = `/video?t=${Date.now()}`;
      }
    }, retryDelay);
  }
}

function handleFeedLoad() {
  if (feedWanted) {
    els.camera.classList.add("is-live");
    setCameraStatus("live · nothing saved");
    // Some browsers fire load on every MJPEG frame; only arm the timer once.
    if (feedStableTimer == null) {
      feedStableTimer = setTimeout(() => {
        feedFailures = 0;
      }, FEED_STABLE_MS);
    }
  }
}

// ---------- start ----------

buildBlocks(els.memBlocks);
buildBlocks(els.diskBlocks);
applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light", false);

els.themeToggle.addEventListener("click", toggleTheme);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", followSystemTheme);

els.feed.addEventListener("error", handleFeedError);
els.feed.addEventListener("load", handleFeedLoad);
els.peekToggle.addEventListener("click", () => {
  const peeking = !feedWanted;
  writeStored("peek", peeking ? "1" : "0");
  setPeek(peeking);
});
setPeek(readStored("peek", "0") === "1");

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopEvents();
  } else {
    startEvents();
  }
});

startEvents();
