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

// el.animate() restarts on every call, which a CSS animation only does when its name changes.
// offset: 0 makes a lone keyframe the starting point; the motion settles on the element's own style.
const MOTIONS = {
  tick: { duration: 450, keyframes: [{ offset: 0, opacity: 0.35, transform: "translateY(0.15em)" }] },
  roll: { duration: 550, keyframes: [{ offset: 0, opacity: 0, transform: "translateY(0.5em)", filter: "blur(3px)" }] },
  swap: { duration: 700, keyframes: [{ offset: 0, opacity: 0, transform: "translateY(0.3em)", filter: "blur(4px)" }] },
  slide: { duration: 600, keyframes: [{ offset: 0, opacity: 0, transform: "translateX(8%)", filter: "blur(4px)" }] },
  rip: { duration: 1000, keyframes: [{ opacity: 0.6, transform: "scale(0.6)" }, { opacity: 0, transform: "scale(1.8)" }] },
};
const MOTION_EASE = getComputedStyle(document.documentElement).getPropertyValue("--ease").trim();
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function replayAnimation(el, name) {
  // styles.css's reduced-motion block only reaches CSS animations, so these check for themselves.
  if (!reducedMotion.matches) {
    const motion = MOTIONS[name];
    el.animate(motion.keyframes, { duration: motion.duration, easing: MOTION_EASE });
  }
}

function setText(el, value) {
  const next = String(value);
  if (el.textContent !== next) {
    el.textContent = next;
    replayAnimation(el, "tick");
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
