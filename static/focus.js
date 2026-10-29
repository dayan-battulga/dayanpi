// The Focus card. State and totals arrive with every stats snapshot (app.js
// re-broadcasts them as "dayanpi:snapshot"); the timeline segments come from
// /api/focus on load, on every state change, and once a minute.

const TIMELINE_REFRESH_MS = 60000;
const DAY_SECONDS = 86400;
const STATE_LABELS = {
  working: "focused",
  phone: "on phone",
  away: "away",
  unknown: "unknown",
};
const STATE_CAPTIONS = {
  working: "at the desk, no phone in sight",
  phone: "phone in hand",
  away: "nobody at the desk",
  unknown: "working it out",
};

const focusEls = {
  card: document.getElementById("focus-card"),
  state: document.getElementById("focus-state"),
  timer: document.getElementById("focus-timer"),
  caption: document.getElementById("focus-caption"),
  working: document.getElementById("focus-working"),
  phone: document.getElementById("focus-phone"),
  pickups: document.getElementById("focus-pickups"),
  snacks: document.getElementById("focus-snacks"),
  best: document.getElementById("focus-best"),
  timeline: document.getElementById("focus-timeline"),
  block: document.getElementById("focus-block"),
  note: document.getElementById("focus-note"),
  signPreview: document.getElementById("sign-preview"),
  signImage: document.getElementById("sign-image"),
};

let latestFocus = null;
let latestFocusAt = 0;
let lastState = null;
let timelineTimer = null;
let blockBusy = false;

function formatClock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(secs).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

function formatShort(seconds) {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) {
    return `${total}s`;
  }
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours === 0) {
    return `${minutes}m`;
  }
  return `${hours}h${String(minutes).padStart(2, "0")}`;
}

function localMidnight() {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return now.getTime() / 1000;
}

function renderTimeline(segments, state, since) {
  const midnight = localMidnight();
  const nowSeconds = Date.now() / 1000;
  focusEls.timeline.replaceChildren();
  const all = segments.slice();
  if (state && since) {
    all.push({ state, start: since, end: null });
  }
  for (const segment of all) {
    const start = Math.max(segment.start, midnight);
    const end = Math.min(segment.end ?? nowSeconds, midnight + DAY_SECONDS);
    if (end <= start || segment.state === "unknown") {
      continue;
    }
    const piece = document.createElement("span");
    piece.className = `focus-segment is-${segment.state}`;
    piece.style.left = `${((start - midnight) / DAY_SECONDS) * 100}%`;
    piece.style.width = `${Math.max(((end - start) / DAY_SECONDS) * 100, 0.15)}%`;
    piece.title = `${segment.state} · ${formatShort(end - start)}`;
    focusEls.timeline.append(piece);
  }
  const marker = document.createElement("span");
  marker.className = "focus-now";
  marker.style.left = `${((nowSeconds - midnight) / DAY_SECONDS) * 100}%`;
  focusEls.timeline.append(marker);
}

async function refreshTimeline() {
  try {
    const response = await fetch("/api/focus", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const body = await response.json();
    renderTimeline(body.segments ?? [], body.state, body.since);
  } catch (error) {
    // The next snapshot or the minute timer will try again.
  }
}

function renderNote(focus) {
  let note = "";
  if (!focus.enabled) {
    note = "models not loaded on the Pi";
  } else if (!focus.camera_ok) {
    note = "no camera frames";
  } else if (focus.block.active) {
    note = `work block running since ${new Date(focus.block.started_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  } else if (focus.app) {
    note = `mac: ${focus.app}`;
  }
  focusEls.note.textContent = note;
}

function renderFocus(focus) {
  focusEls.card.dataset.state = focus.state;
  focusEls.state.textContent = STATE_LABELS[focus.state] ?? focus.state;
  focusEls.caption.textContent = STATE_CAPTIONS[focus.state] ?? "";
  const today = focus.today;
  focusEls.working.textContent = formatShort(today.working_seconds);
  focusEls.phone.textContent = formatShort(today.phone_seconds);
  focusEls.pickups.textContent = String(today.pickups);
  focusEls.snacks.textContent = String(today.snacks);
  focusEls.best.textContent = formatShort(today.longest_streak_seconds);
  focusEls.block.disabled = !focus.enabled || blockBusy;
  focusEls.block.textContent = focus.block.active ? "Stop block" : "Start block";
  focusEls.card.classList.toggle("is-block", focus.block.active);
  renderNote(focus);
  if (focus.sign_png) {
    focusEls.signImage.src = `data:image/png;base64,${focus.sign_png}`;
    focusEls.signPreview.hidden = false;
  }
}

function tickTimer() {
  if (latestFocus == null) {
    return;
  }
  const drift = (Date.now() - latestFocusAt) / 1000;
  focusEls.timer.textContent = formatClock(latestFocus.seconds_in_state + drift);
}

async function toggleBlock() {
  if (blockBusy) {
    return;
  }
  blockBusy = true;
  focusEls.block.disabled = true;
  try {
    await fetch("/api/focus/block", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "toggle" }),
    });
  } catch (error) {
    // The next snapshot shows the real state either way.
  } finally {
    blockBusy = false;
    if (latestFocus != null) {
      focusEls.block.disabled = !latestFocus.enabled;
    }
  }
}

window.addEventListener("dayanpi:snapshot", (event) => {
  const focus = event.detail?.focus;
  if (focus == null) {
    return;
  }
  latestFocus = focus;
  latestFocusAt = Date.now();
  renderFocus(focus);
  tickTimer();
  if (focus.state !== lastState) {
    lastState = focus.state;
    refreshTimeline();
  }
});

focusEls.block.addEventListener("click", toggleBlock);

setInterval(tickTimer, 1000);
timelineTimer = setInterval(refreshTimeline, TIMELINE_REFRESH_MS);
refreshTimeline();
