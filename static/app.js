const TEMP_ELEVATED_C = 70;
const TEMP_CRITICAL_C = 80;
const CPU_ELEVATED_PCT = 70;
const CPU_CRITICAL_PCT = 90;
const MAX_POINTS = 120; // ~2 minutes at 1 Hz
const CHART_HEIGHT = 152;

const els = {
  status: document.getElementById("status"),
  statusLabel: document.querySelector("#status .status-label"),
  powerRail: document.getElementById("power-rail"),
  temp: document.getElementById("temp"),
  tempMeter: document.getElementById("temp-meter"),
  tempFill: document.getElementById("temp-fill"),
  cpu: document.getElementById("cpu"),
  cpuMeter: document.getElementById("cpu-meter"),
  cpuFill: document.getElementById("cpu-fill"),
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
  feed: document.getElementById("feed"),
  chartCpu: document.getElementById("chart-cpu"),
  chartTemp: document.getElementById("chart-temp"),
  chartMem: document.getElementById("chart-mem"),
};

const history = [];
let events = null;
let charts = null;

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

function setMeter(meter, fill, percent, { vertical = false, level = "nominal" } = {}) {
  const clamped = Math.max(0, Math.min(100, percent));
  if (vertical) {
    fill.style.width = "100%";
    fill.style.height = `${clamped}%`;
  } else {
    fill.style.height = "100%";
    fill.style.width = `${clamped}%`;
  }
  meter.dataset.level = level;
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
  const tempLevel = thresholdLevel(temp, TEMP_ELEVATED_C, TEMP_CRITICAL_C);
  setText(els.temp, temp.toFixed(1));
  els.temp.dataset.level = tempLevel;
  // Temp bar is scaled to 100°C max.
  setMeter(els.tempMeter, els.tempFill, temp, {
    vertical: true,
    level: tempLevel,
  });

  setText(els.uptime, formattedUptime(stats.uptime_seconds));

  const memLevel = thresholdLevel(
    stats.memory.percent_used,
    CPU_ELEVATED_PCT,
    CPU_CRITICAL_PCT,
  );
  setText(els.memAvailable, stats.memory.available_mb.toFixed(1));
  setText(els.memTotal, stats.memory.total_mb.toFixed(1));
  setText(els.memPercent, stats.memory.percent_used.toFixed(1));
  setMeter(els.memMeter, els.memFill, stats.memory.percent_used, {
    level: memLevel,
  });

  const diskLevel = thresholdLevel(
    stats.disk.percent_used,
    CPU_ELEVATED_PCT,
    CPU_CRITICAL_PCT,
  );
  setText(els.diskFree, stats.disk.free_gb.toFixed(1));
  setText(els.diskTotal, stats.disk.total_gb.toFixed(1));
  setText(els.diskPercent, stats.disk.percent_used.toFixed(1));
  setMeter(els.diskMeter, els.diskFill, stats.disk.percent_used, {
    level: diskLevel,
  });

  if (stats.rates == null) {
    setText(els.cpu, "--");
    els.cpu.dataset.level = "nominal";
    setMeter(els.cpuMeter, els.cpuFill, 0, { vertical: true, level: "nominal" });
    setText(els.rx, "--");
    setText(els.tx, "--");
  } else {
    const cpu = stats.rates.cpu_percent;
    const cpuLevel = thresholdLevel(cpu, CPU_ELEVATED_PCT, CPU_CRITICAL_PCT);
    setText(els.cpu, cpu.toFixed(1));
    els.cpu.dataset.level = cpuLevel;
    setMeter(els.cpuMeter, els.cpuFill, cpu, {
      vertical: true,
      level: cpuLevel,
    });
    setText(els.rx, formattedBytes(stats.rates.rx_kbps));
    setText(els.tx, formattedBytes(stats.rates.tx_kbps));
  }

  renderThrottle(stats.throttle);
}

function pushHistory(sample) {
  history.push({
    t: Date.now() / 1000,
    sample,
  });
  if (history.length > MAX_POINTS) {
    history.shift();
  }
}

function chartData() {
  const times = [];
  const cpu = [];
  const temp = [];
  const tempLimit = [];
  const mem = [];

  for (const point of history) {
    times.push(point.t);
    const rates = point.sample.rates;
    cpu.push(rates == null ? null : rates.cpu_percent);
    temp.push(point.sample.temperature_celsius);
    tempLimit.push(TEMP_CRITICAL_C);
    mem.push(point.sample.memory.percent_used);
  }

  return { times, cpu, temp, tempLimit, mem };
}

function baseAxis() {
  return {
    stroke: "#6b7280",
    grid: { stroke: "rgba(20, 23, 28, 0.08)" },
    ticks: { stroke: "rgba(20, 23, 28, 0.12)" },
    font: "11px JetBrains Mono, monospace",
  };
}

function createChart(target, series, yRange) {
  const width = Math.max(target.clientWidth || 280, 160);
  return new uPlot(
    {
      width,
      height: CHART_HEIGHT,
      cursor: { show: true, x: true, y: false },
      legend: { show: false },
      scales: {
        x: { time: true },
        y: { auto: false, range: yRange },
      },
      axes: [
        {
          ...baseAxis(),
          space: 56,
          values: (_u, splits) =>
            splits.map((t) => {
              const date = new Date(t * 1000);
              return `${String(date.getMinutes()).padStart(2, "0")}:${String(
                date.getSeconds(),
              ).padStart(2, "0")}`;
            }),
        },
        {
          ...baseAxis(),
          size: 42,
        },
      ],
      series,
    },
    [[], ...series.slice(1).map(() => [])],
    target,
  );
}

function ensureCharts() {
  if (charts != null || typeof uPlot === "undefined") {
    return;
  }

  charts = {
    cpu: createChart(
      els.chartCpu,
      [
        {},
        {
          label: "CPU",
          stroke: "#0f766e",
          width: 2,
          spanGaps: false,
        },
      ],
      [0, 100],
    ),
    temp: createChart(
      els.chartTemp,
      [
        {},
        {
          label: "Temp",
          stroke: "#b45309",
          width: 2,
          spanGaps: false,
        },
        {
          label: "Throttle",
          stroke: "#be123c",
          width: 1,
          dash: [4, 4],
          spanGaps: true,
        },
      ],
      [30, 90],
    ),
    mem: createChart(
      els.chartMem,
      [
        {},
        {
          label: "Memory",
          stroke: "#14171c",
          width: 2,
          spanGaps: false,
        },
      ],
      [0, 100],
    ),
  };
}

function renderCharts() {
  ensureCharts();
  if (charts == null || history.length === 0) {
    return;
  }

  const data = chartData();
  charts.cpu.setData([data.times, data.cpu]);
  charts.temp.setData([data.times, data.temp, data.tempLimit]);
  charts.mem.setData([data.times, data.mem]);
}

function resizeCharts() {
  if (charts == null) {
    return;
  }
  for (const [key, el] of [
    ["cpu", els.chartCpu],
    ["temp", els.chartTemp],
    ["mem", els.chartMem],
  ]) {
    const width = Math.max(el.clientWidth || 280, 160);
    charts[key].setSize({ width, height: CHART_HEIGHT });
  }
}

function startEvents() {
  if (events != null) {
    return;
  }

  events = new EventSource("/api/stream");
  events.onmessage = (event) => {
    const sample = JSON.parse(event.data);
    pushHistory(sample);
    render(sample);
    renderCharts();
    setStatus("connected");
  };
  // Browser already reconnects — only update the indicator.
  events.onerror = () => {
    setStatus("reconnecting");
  };
}

function stopEvents() {
  if (events == null) {
    return;
  }
  events.close();
  events = null;
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopEvents();
  } else {
    startEvents();
  }
});

window.addEventListener("resize", () => {
  resizeCharts();
});

els.feed.onerror = () => {
  els.feed.closest(".cell-feed")?.classList.remove("is-live");
  els.feed.closest(".cell-feed")?.classList.add("is-reconnecting");
  setTimeout(() => {
    els.feed.src = "/video?t=" + Date.now();
  }, 2000);
};

els.feed.onload = () => {
  const card = els.feed.closest(".cell-feed");
  card?.classList.remove("is-reconnecting");
  card?.classList.add("is-live");
};

startEvents();

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
