const INTERVAL_MS = 2000;

const TEMP_ELEVATED_C = 70;
const TEMP_CRITICAL_C = 80;
const CPU_ELEVATED_PCT = 70;
const CPU_CRITICAL_PCT = 90;

const els = {
  status: document.getElementById("status"),
  statusLabel: document.querySelector("#status .status-label"),
  powerRail: document.getElementById("power-rail"),
  temp: document.getElementById("temp"),
  cpu: document.getElementById("cpu"),
  memMeter: document.getElementById("mem-meter"),
  memFill: document.getElementById("mem-fill"),
  memAvailable: document.getElementById("mem-available"),
  memTotal: document.getElementById("mem-total"),
  memPercent: document.getElementById("mem-percent"),
  diskMeter: document.getElementById("disk-meter"),
  diskFill: document.getElementById("disk-fill"),
  diskFree: document.getElementById("disk-free"),
  diskTotal: document.getElementById("disk-total"),
  diskPercent: document.getElementById("disk-percent"),
  rx: document.getElementById("rx"),
  tx: document.getElementById("tx"),
  uptime: document.getElementById("uptime"),
  throttle: document.getElementById("throttle"),
};

let timerId = null;

function setStatus(state) {
  els.status.className = state;
  els.statusLabel.textContent = state;
}

function thresholdLevel(value, elevatedAt, criticalAt) {
  if (value >= criticalAt) {
    return "critical";
  }
  if (value >= elevatedAt) {
    return "elevated";
  }
  return "nominal";
}

function setText(el, value) {
  const next = String(value);
  if (el.textContent === next) {
    return;
  }
  el.textContent = next;
  el.classList.remove("tick");
  // Force reflow so the animation can replay on rapid updates.
  void el.offsetWidth;
  el.classList.add("tick");
}

function setMeter(meter, fill, percent) {
  const clamped = Math.max(0, Math.min(100, percent));
  fill.style.width = `${clamped}%`;
  meter.setAttribute("aria-valuenow", String(Math.round(clamped)));
}

function setPowerRailState(stateClass) {
  els.powerRail.classList.remove(
    "throttle-ok",
    "throttle-sticky",
    "throttle-live",
  );
  els.powerRail.classList.add(stateClass);
}

function renderThrottle(throttle) {
  const live = [];
  const sticky = [];

  if (throttle.is_undervoltage) {
    live.push("UNDERVOLTAGE");
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

  document.body.classList.toggle("undervoltage-live", throttle.is_undervoltage);

  if (live.length === 0 && sticky.length === 0) {
    setText(els.throttle, "all clear");
    setPowerRailState("throttle-ok");
    return;
  }

  const parts = [];
  if (live.length > 0) {
    parts.push(`NOW ${live.join(" · ")}`);
  }
  if (sticky.length > 0) {
    parts.push(`since boot: ${sticky.join(", ")}`);
  }

  setText(els.throttle, parts.join(" · "));
  setPowerRailState(live.length > 0 ? "throttle-live" : "throttle-sticky");
}

function render(stats) {
  const temp = stats.temperature_celsius;
  setText(els.temp, temp.toFixed(1));
  els.temp.dataset.level = thresholdLevel(
    temp,
    TEMP_ELEVATED_C,
    TEMP_CRITICAL_C,
  );

  setText(els.uptime, formattedUptime(stats.uptime_seconds));

  setText(els.memAvailable, stats.memory.available_mb.toFixed(1));
  setText(els.memTotal, stats.memory.total_mb.toFixed(1));
  setText(els.memPercent, stats.memory.percent_used.toFixed(1));
  setMeter(els.memMeter, els.memFill, stats.memory.percent_used);

  setText(els.diskFree, stats.disk.free_gb.toFixed(1));
  setText(els.diskTotal, stats.disk.total_gb.toFixed(1));
  setText(els.diskPercent, stats.disk.percent_used.toFixed(1));
  setMeter(els.diskMeter, els.diskFill, stats.disk.percent_used);

  if (stats.rates == null) {
    setText(els.cpu, "--");
    els.cpu.dataset.level = "nominal";
    setText(els.rx, "--");
    setText(els.tx, "--");
  } else {
    const cpu = stats.rates.cpu_percent;
    setText(els.cpu, cpu.toFixed(1));
    els.cpu.dataset.level = thresholdLevel(
      cpu,
      CPU_ELEVATED_PCT,
      CPU_CRITICAL_PCT,
    );
    setText(els.rx, formattedBytes(stats.rates.rx_kbps));
    setText(els.tx, formattedBytes(stats.rates.tx_kbps));
  }

  renderThrottle(stats.throttle);
}

async function fetchStats() {
  try {
    const response = await fetch("/api/stats");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const stats = await response.json();
    render(stats);
    setStatus("connected");
  } catch (error) {
    console.error(error);
    setStatus("reconnecting");
  }
}

async function loop() {
  if (document.hidden) {
    return;
  }

  await fetchStats();

  if (!document.hidden) {
    timerId = setTimeout(loop, INTERVAL_MS);
  }
}

function startLoop() {
  clearTimeout(timerId);
  loop();
}

function stopLoop() {
  clearTimeout(timerId);
  timerId = null;
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopLoop();
  } else {
    startLoop();
  }
});

startLoop();

function formattedUptime(seconds) {
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${days}d ${hours}h ${minutes}m`;
}

function formattedBytes(kbps) {
  if (kbps >= 1000) {
    return `${(kbps / 1000).toFixed(1)} Mb/s`;
  }
  return `${kbps.toFixed(1)} kb/s`;
}
