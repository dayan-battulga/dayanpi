// The Focus card, the detector readings, the LED sign and the Today list.
// State, totals and the latest check arrive with every stats snapshot (app.js
// re-broadcasts them as "dayanpi:snapshot"); the segments behind the timeline and
// the Today list come from /api/focus on load, on every state change, and once a minute.

const TIMELINE_REFRESH_MS = 60000;
const DAY_SECONDS = 86400;
const DAY_START_HOUR = 6;
const HOUR_LABEL_STEP = 3;
const TODAY_LIST_LENGTH = 5;
const SEGMENT_STAGGER_MS = 60;
const MIN_SEGMENT_SHARE = 0.4; // % of the bar, so a one-minute pickup still shows
const MERGE_GAP_S = 60;
const STATE_COPY = {
  working: { chip: "Working", label: "Focused" },
  phone: { chip: "On phone", label: "Phone up" },
  away: { chip: "Away", label: "Stepped away" },
  unknown: { chip: "Unknown", label: "Waiting" },
};
const SIGN_PAGES = { now: "Now", today: "Today", summary: "Day done" };

const focusEls = {
  card: document.getElementById("focus-card"),
  state: document.getElementById("focus-state"),
  blockChip: document.getElementById("focus-block-chip"),
  date: document.getElementById("focus-date"),
  label: document.getElementById("focus-label"),
  timer: document.getElementById("focus-timer"),
  caption: document.getElementById("focus-caption"),
  block: document.getElementById("focus-block"),
  timeline: document.getElementById("focus-timeline"),
  hours: document.getElementById("focus-hours"),
  working: document.getElementById("focus-working"),
  phone: document.getElementById("focus-phone"),
  pickups: document.getElementById("focus-pickups"),
  ripple: document.getElementById("focus-ripple"),
  free: document.getElementById("focus-free"),
  snacks: document.getElementById("focus-snacks"),
  best: document.getElementById("focus-best"),
  checkMs: document.getElementById("check-ms"),
  signImage: document.getElementById("sign-image"),
  signEmpty: document.getElementById("sign-empty"),
  signPage: document.getElementById("sign-page"),
  signMode: document.getElementById("sign-mode"),
  voice: document.getElementById("voice"),
  mac: document.getElementById("mac"),
  todayList: document.getElementById("today-list"),
};

const readingRows = Array.from(document.querySelectorAll(".reading")).map((row) => ({
  key: row.dataset.key,
  value: row.querySelector(".reading-value"),
  fill: row.querySelector(".reading-fill"),
}));

let latestFocus = null;
let latestFocusAt = 0;
let lastState = null;
let lastPickups = null;
let todaySegments = [];
let timelineDrawn = false;
let timelineStartHour = null;
let liveSegment = null;
let nowCursor = null;
let todaySignature = "";
let todayMetas = [];
let blockBusy = false;

function readLocalMidnight() {
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const seconds = midnight.getTime() / 1000;
  return seconds;
}

function formatClock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, "0");
  const text = hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
  return text;
}

// Digits are matched from the right, so the seconds keep their spans when an hour digit appears.
function renderDigits(container, text) {
  while (container.children.length > text.length) {
    container.firstElementChild.remove();
  }
  while (container.children.length < text.length) {
    container.prepend(document.createElement("span"));
  }
  Array.from(text).forEach((char, index) => {
    const span = container.children[index];
    if (span.textContent !== char) {
      span.textContent = char;
      if (char === ":") {
        span.className = "digit-sep";
      } else {
        span.classList.remove("digit-sep");
        span.classList.add("digit");
        replayAnimation(span, "roll-a", "roll-b");
      }
    }
  });
}

// Drops the unknown stretches and joins short gaps, so a camera blip doesn't split a streak
// but a Pi that was off for an hour still shows as a hole.
function mergeKnownSegments(segments, midnight) {
  const merged = [];
  for (const segment of segments) {
    const ends = segment.end ?? Infinity;
    if (segment.state !== "unknown" && ends > midnight) {
      const start = Math.max(segment.start, midnight);
      const previous = merged[merged.length - 1];
      if (previous != null && previous.state === segment.state && start - previous.end <= MERGE_GAP_S) {
        previous.end = segment.end;
      } else {
        merged.push({ state: segment.state, start, end: segment.end });
      }
    }
  }
  return merged;
}

function describeCaption(focus) {
  let caption = "Working out what you're up to";
  if (!focus.enabled) {
    caption = "The detector isn't running on the Pi";
  } else if (!focus.camera_ok) {
    caption = "No camera frames · time isn't counted";
  } else if (focus.state === "working") {
    caption = `Current streak · since ${formatTimeOfDay(focus.since)}`;
  } else if (focus.state === "phone") {
    caption = "Counting toward today's phone time";
  } else if (focus.state === "away") {
    caption = `Away since ${formatTimeOfDay(focus.since)}`;
  }
  return caption;
}

function describeVoice(voice) {
  let text = "off";
  if (voice != null && voice.enabled) {
    text = voice.backend;
  } else if (voice != null && voice.problem) {
    text = "error";
  }
  return text;
}

// ---------- timeline ----------

function renderHours(startHour) {
  const hours = [startHour];
  for (let hour = Math.ceil((startHour + 1) / HOUR_LABEL_STEP) * HOUR_LABEL_STEP; hour < 24; hour += HOUR_LABEL_STEP) {
    hours.push(hour);
  }
  hours.push(24);
  focusEls.hours.replaceChildren(
    ...hours.map((hour) => {
      const label = document.createElement("span");
      label.textContent = String(hour);
      label.style.left = `${((hour - startHour) / (24 - startHour)) * 100}%`;
      return label;
    }),
  );
}

function renderTimeline(now) {
  const midnight = readLocalMidnight();
  const known = mergeKnownSegments(todaySegments, midnight);
  const firstHour = known.length > 0 ? Math.floor((known[0].start - midnight) / 3600) : DAY_START_HOUR;
  const startHour = Math.max(0, Math.min(DAY_START_HOUR, firstHour));
  const windowStart = midnight + startHour * 3600;
  const windowSpan = DAY_SECONDS - startHour * 3600;
  if (startHour !== timelineStartHour) {
    timelineStartHour = startHour;
    renderHours(startHour);
  }

  liveSegment = null;
  const pieces = known.map((segment, index) => {
    const piece = document.createElement("div");
    const end = segment.end ?? now;
    piece.className = `segment is-${segment.state}`;
    piece.classList.toggle("is-live", segment.end == null);
    piece.classList.toggle("is-first", index === 0);
    piece.style.left = `${((segment.start - windowStart) / windowSpan) * 100}%`;
    piece.style.width = `${Math.max(((end - segment.start) / windowSpan) * 100, MIN_SEGMENT_SHARE)}%`;
    piece.title = `${STATE_COPY[segment.state].chip} · ${formatTimeOfDay(segment.start)} · ${formatDuration(end - segment.start)}`;
    if (!timelineDrawn) {
      piece.classList.add("grow");
      piece.style.animationDelay = `${200 + index * SEGMENT_STAGGER_MS}ms`;
    }
    if (segment.end == null) {
      liveSegment = { el: piece, start: segment.start, windowStart, windowSpan };
    }
    return piece;
  });

  nowCursor = document.createElement("div");
  nowCursor.className = timelineDrawn ? "now-cursor" : "now-cursor glide";
  nowCursor.dataset.windowStart = String(windowStart);
  nowCursor.dataset.windowSpan = String(windowSpan);
  nowCursor.style.left = `${Math.min(100, ((now - windowStart) / windowSpan) * 100)}%`;
  focusEls.timeline.replaceChildren(...pieces, nowCursor);
  timelineDrawn = true;
}

function moveTimelineNow(now) {
  if (liveSegment != null) {
    const share = ((now - liveSegment.start) / liveSegment.windowSpan) * 100;
    liveSegment.el.style.width = `${Math.max(share, MIN_SEGMENT_SHARE)}%`;
  }
  if (nowCursor != null) {
    const windowStart = Number(nowCursor.dataset.windowStart);
    const windowSpan = Number(nowCursor.dataset.windowSpan);
    nowCursor.style.left = `${Math.min(100, ((now - windowStart) / windowSpan) * 100)}%`;
  }
}

// ---------- today list ----------

function describeSegment(segment, previous) {
  let title = "Stepped away";
  if (segment.state === "phone") {
    title = "Picked up your phone";
  } else if (segment.state === "working" && previous?.state === "away") {
    title = "Back at the desk";
  } else if (segment.state === "working" && previous?.state === "phone") {
    title = "Back to work";
  } else if (segment.state === "working") {
    title = "Sat down to work";
  }
  return title;
}

function describeLength(segment, now) {
  const length = formatDuration((segment.end ?? now) - segment.start);
  const text = segment.end == null ? `now · ${length}` : length;
  return text;
}

function renderToday(now) {
  const known = mergeKnownSegments(todaySegments, readLocalMidnight());
  const recent = known.slice(-TODAY_LIST_LENGTH).reverse();
  const signature = recent.map((segment) => `${segment.state}@${segment.start}:${segment.end == null}`).join("|");
  if (signature !== todaySignature) {
    todaySignature = signature;
    todayMetas = [];
    const rows = recent.map((segment, index) => {
      const row = document.createElement("li");
      const time = document.createElement("span");
      const dot = document.createElement("span");
      const what = document.createElement("span");
      const meta = document.createElement("span");
      const previous = known[known.length - 1 - index - 1];
      row.style.animationDelay = `${index * SEGMENT_STAGGER_MS}ms`;
      time.className = "today-time mono";
      time.textContent = formatTimeOfDay(segment.start);
      dot.className = `today-dot is-${segment.state}`;
      what.className = "today-what";
      what.textContent = describeSegment(segment, previous);
      meta.className = "today-meta mono";
      row.append(time, dot, what, meta);
      todayMetas.push({ el: meta, segment });
      return row;
    });
    if (rows.length === 0) {
      const empty = document.createElement("li");
      empty.className = "today-empty muted";
      empty.textContent = "Nothing yet today.";
      rows.push(empty);
    }
    focusEls.todayList.replaceChildren(...rows);
  }
  for (const item of todayMetas) {
    item.el.textContent = describeLength(item.segment, now);
  }
}

function describePhoneFree(focus, now) {
  const phoneEnds = todaySegments
    .filter((segment) => segment.state === "phone" && segment.end != null)
    .map((segment) => segment.end);
  let text = "--";
  if (focus.state === "phone") {
    text = "on it now";
  } else if (phoneEnds.length > 0) {
    text = formatDuration(now - Math.max(...phoneEnds));
  } else if (focus.today.first_seen != null) {
    text = "all day";
  }
  return text;
}

async function refreshTimeline() {
  try {
    const response = await fetch("/api/focus", { cache: "no-store" });
    if (response.ok) {
      const body = await response.json();
      todaySegments = body.segments ?? [];
      const now = Date.now() / 1000;
      renderTimeline(now);
      renderToday(now);
    }
  } catch (error) {
    // The next state change or the minute timer tries again.
  }
}

// ---------- snapshot ----------

function renderReadings(focus) {
  const check = focus.camera_ok ? focus.last_check : null;
  for (const row of readingRows) {
    const value = check == null ? null : check[row.key];
    row.value.textContent = value == null ? "—" : value.toFixed(2);
    row.fill.style.width = `${value == null ? 0 : Math.round(value * 100)}%`;
  }
  let speed = "detector off";
  if (check != null) {
    speed = `~${Math.round(check.elapsed_ms)} ms each`;
  } else if (focus.enabled) {
    speed = "no frames";
  }
  focusEls.checkMs.textContent = speed;
}

function renderSign(focus) {
  const sign = focus.sign ?? { mode: "off", page: null };
  focusEls.signMode.textContent = sign.mode;
  focusEls.signPage.textContent = SIGN_PAGES[sign.page] ?? "";
  if (sign.mode === "off") {
    focusEls.signImage.hidden = true;
    focusEls.signEmpty.hidden = false;
    focusEls.signEmpty.textContent = "The sign is off";
  } else if (focus.sign_png) {
    focusEls.signImage.src = `data:image/png;base64,${focus.sign_png}`;
    focusEls.signImage.hidden = false;
    focusEls.signEmpty.hidden = true;
  }
}

function renderFocus(focus) {
  const copy = STATE_COPY[focus.state] ?? STATE_COPY.unknown;
  const today = focus.today;
  focusEls.card.dataset.state = focus.state;
  focusEls.state.textContent = copy.chip;
  if (focusEls.label.textContent !== copy.label) {
    focusEls.label.textContent = copy.label;
    replayAnimation(focusEls.label, "swap-a", "swap-b");
  }
  focusEls.caption.textContent = describeCaption(focus);
  focusEls.blockChip.hidden = !focus.block.active;
  focusEls.block.textContent = focus.block.active ? "End block" : "Start block";
  focusEls.block.classList.toggle("button-primary", !focus.block.active);
  focusEls.block.classList.toggle("button-ghost", focus.block.active);
  focusEls.block.disabled = !focus.enabled || blockBusy;

  setText(focusEls.working, formatDuration(today.working_seconds));
  setText(focusEls.phone, formatDuration(today.phone_seconds));
  setText(focusEls.pickups, today.pickups);
  setText(focusEls.snacks, today.snacks);
  setText(focusEls.best, formatDuration(today.longest_streak_seconds));
  if (lastPickups != null && today.pickups > lastPickups) {
    replayAnimation(focusEls.ripple, "rip-a", "rip-b");
  }
  lastPickups = today.pickups;

  focusEls.voice.textContent = describeVoice(focus.voice);
  focusEls.mac.textContent = focus.app || "—";
  renderReadings(focus);
  renderSign(focus);
}

function tick() {
  const now = Date.now() / 1000;
  const date = new Date();
  focusEls.date.textContent = `${date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} · ${formatTimeOfDay(now)}`;
  if (latestFocus != null) {
    const drift = (Date.now() - latestFocusAt) / 1000;
    renderDigits(focusEls.timer, formatClock(latestFocus.seconds_in_state + drift));
    setText(focusEls.free, describePhoneFree(latestFocus, now));
  }
  moveTimelineNow(now);
}

async function toggleBlock() {
  if (!blockBusy) {
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
      focusEls.block.disabled = latestFocus == null || !latestFocus.enabled;
    }
  }
}

window.addEventListener("dayanpi:snapshot", (event) => {
  const focus = event.detail?.focus;
  if (focus != null) {
    latestFocus = focus;
    latestFocusAt = Date.now();
    renderFocus(focus);
    tick();
    if (focus.state !== lastState) {
      lastState = focus.state;
      refreshTimeline();
    }
  }
});

// The stream only carries the sign picture when it changes, so a fresh page asks once.
function loadSignPicture() {
  focusEls.signImage.addEventListener(
    "load",
    () => {
      focusEls.signImage.hidden = false;
      focusEls.signEmpty.hidden = true;
    },
    { once: true },
  );
  focusEls.signImage.src = `/api/sign.png?t=${Date.now()}`;
}

focusEls.block.addEventListener("click", toggleBlock);
focusEls.timer.replaceChildren();
loadSignPicture();

tick();
setInterval(tick, 1000);
setInterval(refreshTimeline, TIMELINE_REFRESH_MS);
refreshTimeline();
