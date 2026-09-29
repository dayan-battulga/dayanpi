const SEND_INTERVAL_MS = 150;
const REQUEST_TIMEOUT_MS = 1000;
const DRIVE_KEYS = ["KeyW", "KeyA", "KeyS", "KeyD"];

// "forward,turn" → wheel command. forward = W − S, turn = D − A.
const COMMANDS = {
  "0,0": { left: 0, right: 0 },
  "1,0": { left: 1, right: 1 },
  "-1,0": { left: -1, right: -1 },
  "0,-1": { left: -1, right: 1 },
  "0,1": { left: 1, right: -1 },
  "1,-1": { left: 0.4, right: 1 },
  "1,1": { left: 1, right: 0.4 },
  "-1,-1": { left: -0.4, right: -1 },
  "-1,1": { left: -1, right: -0.4 },
};

const els = {
  card: document.getElementById("drive-card"),
  state: document.getElementById("drive-state"),
  left: document.getElementById("drive-left"),
  right: document.getElementById("drive-right"),
  error: document.getElementById("drive-error"),
  keys: document.querySelectorAll("#drive-card [data-key]"),
  pad: document.querySelectorAll(".drive-pad button"),
};

const held = new Set();
let sendTimer = null;
let inFlight = false;
let pending = null;
let lastError = "";
let motorsUnavailable = false;

function computeCommand() {
  const forward = held.has("KeyW") - held.has("KeyS");
  const turn = held.has("KeyD") - held.has("KeyA");
  const command = COMMANDS[`${forward},${turn}`];
  return command;
}

function formatSpeed(value) {
  const text = (value >= 0 ? "+" : "") + value.toFixed(2);
  return text;
}

function renderCard(command) {
  const driving = command.left !== 0 || command.right !== 0;
  els.left.textContent = formatSpeed(command.left);
  els.right.textContent = formatSpeed(command.right);
  els.error.textContent = lastError;
  els.card.classList.toggle("is-driving", driving && !lastError);
  els.card.classList.toggle("is-error", Boolean(lastError));
  els.state.textContent = motorsUnavailable
    ? "unavailable"
    : lastError
      ? "error"
      : driving
        ? "driving"
        : "idle";
  for (const keyEl of els.keys) {
    keyEl.classList.toggle("is-held", held.has(keyEl.dataset.key));
  }
}

// One request at a time, newest command wins. Parallel requests can land out
// of order, and a late "drive" arriving after the "stop" would move the rover.
function sendCommand(command) {
  if (inFlight) {
    pending = command;
  } else {
    inFlight = true;
    fetch("/api/drive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(command),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    })
      .then((response) => {
        motorsUnavailable = response.status === 503;
        lastError = response.ok
          ? ""
          : motorsUnavailable
            ? "motors unavailable (the Pi couldn't open the motor pins; check its logs)"
            : `drive failed: HTTP ${response.status}`;
      })
      .catch((error) => {
        motorsUnavailable = false;
        lastError = `drive failed: ${error.name === "TimeoutError" ? "timed out" : "network error"}`;
      })
      .finally(() => {
        inFlight = false;
        renderCard(computeCommand());
        if (pending != null) {
          const next = pending;
          pending = null;
          sendCommand(next);
        }
      });
  }
}

function updateDrive() {
  const command = computeCommand();
  renderCard(command);
  sendCommand(command);
  if (held.size > 0 && sendTimer == null) {
    sendTimer = setInterval(() => sendCommand(computeCommand()), SEND_INTERVAL_MS);
  } else if (held.size === 0 && sendTimer != null) {
    clearInterval(sendTimer);
    sendTimer = null;
  }
}

function releaseAll() {
  held.clear();
  updateDrive();
}

window.addEventListener("keydown", (event) => {
  // macOS drops the keyup of any key released while Cmd is down, which would
  // leave W stuck "held" and the rover driving. Any modifier = full stop.
  const modified = event.metaKey || event.ctrlKey || event.altKey;
  if (!event.repeat && modified) {
    releaseAll();
  } else if (!event.repeat && DRIVE_KEYS.includes(event.code)) {
    held.add(event.code);
    updateDrive();
  }
});

window.addEventListener("keyup", (event) => {
  if (held.delete(event.code)) {
    updateDrive();
  }
});

function pressPad(event) {
  // Stops the long-press callout and the emulated mouse events that follow a touch.
  event.preventDefault();
  // Touch pointers are implicitly captured, which suppresses pointerleave;
  // release it so sliding a thumb off the button counts as letting go.
  if (event.currentTarget.hasPointerCapture(event.pointerId)) {
    event.currentTarget.releasePointerCapture(event.pointerId);
  }
  held.add(event.currentTarget.dataset.key);
  updateDrive();
}

function releasePad(event) {
  // Touch fires pointerleave right after pointerup; delete() is false the second time.
  if (held.delete(event.currentTarget.dataset.key)) {
    updateDrive();
  }
}

for (const button of els.pad) {
  button.addEventListener("pointerdown", pressPad);
  button.addEventListener("pointerup", releasePad);
  button.addEventListener("pointercancel", releasePad);
  button.addEventListener("pointerleave", releasePad);
  button.addEventListener("contextmenu", (event) => event.preventDefault());
}

window.addEventListener("blur", releaseAll);

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    releaseAll();
  }
});

// One stop on page load: harmless, and it tells the card straight away
// whether the motors are available.
sendCommand({ left: 0, right: 0 });
