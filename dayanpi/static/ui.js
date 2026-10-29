// Helpers shared by app.js and focus.js. Plain scripts, so this one loads first.

const STORAGE_PREFIX = "dayanpi.";

function readStored(key, fallback) {
  let value = fallback;
  try {
    const stored = window.localStorage.getItem(STORAGE_PREFIX + key);
    if (stored !== null) {
      value = stored;
    }
  } catch (error) {
    // Private windows and blocked site data throw here; the fallback is fine.
  }
  return value;
}

function writeStored(key, value) {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, value);
  } catch (error) {
    // Same as above: a preference that doesn't stick isn't worth an error.
  }
}

// Swapping between two identical keyframe classes restarts the animation
// without forcing a layout read on every update.
function replayAnimation(el, first, second) {
  const next = el.classList.contains(first) ? second : first;
  el.classList.remove(first, second);
  el.classList.add(next);
}

function setText(el, value) {
  const next = String(value);
  if (el.textContent !== next) {
    el.textContent = next;
    replayAnimation(el, "tick-a", "tick-b");
  }
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  let text = `${total}s`;
  if (hours > 0) {
    text = `${hours}h ${String(minutes).padStart(2, "0")}m`;
  } else if (total >= 60) {
    text = `${minutes}m`;
  }
  return text;
}

function formatTimeOfDay(epochSeconds) {
  const text = new Date(epochSeconds * 1000)
    .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    .toLowerCase();
  return text;
}
